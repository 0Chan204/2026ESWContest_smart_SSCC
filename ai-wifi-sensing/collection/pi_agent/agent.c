#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
/* USB acquisition stays independent of HTTP latency. One reader per ESP32.
 * Raw lines are spooled to disk; parsing and scientific processing run on PC. */
#include <curl/curl.h>
#include <json-c/json.h>
#include <pthread.h>
#include <stdatomic.h>
#include <termios.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <dirent.h>
#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <ctype.h>

#define MAX_DEVICES 64
#define LINE_SIZE 32768
#define PATH_SIZE 4096
#define FILE_LIMIT (48 * 1024 * 1024)

typedef struct {
    char id[65], port[512], configured_port[512], mac[32];
    int baud;
} Device;
typedef struct {
    Device device;
    pthread_t thread;
    bool launched;
    int fd;
    FILE *output;
    _Atomic unsigned long rows;
    _Atomic bool finished;
    unsigned long rejected;
    char selected_mac[32];
    double last_packet;
    char error[256];
    double first, last;
    int index;
} Reader;

static char server_url[1024], pi_id[65], token[256], spool[PATH_SIZE];
static Device devices[MAX_DEVICES];
static Reader readers[MAX_DEVICES];
static int device_count, reader_count;
static int spool_lock = -1;
static bool simulate;
static volatile sig_atomic_t quitting;
static _Atomic bool stop_readers;
static _Atomic double start_mono, end_mono;
static double epoch_offset, last_rtt;
static char active_job[65], active_dir[PATH_SIZE];
static bool ready_sent;
static char prepare_error[256];
static bool sample_mode;
static unsigned long packet_target;
static double idle_timeout;
static json_object *port_cache;
static char port_cache_path[PATH_SIZE];

static double mono(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void pause_ms(int ms) {
    struct timespec t = {.tv_sec = ms / 1000, .tv_nsec = (ms % 1000) * 1000000L};
    nanosleep(&t, NULL);
}
static void on_signal(int sig) { (void)sig; quitting = 1; }
static void die(const char *message) { fprintf(stderr, "%s: %s\n", message, strerror(errno)); exit(1); }
static json_object *field(json_object *o, const char *key) {
    json_object *v = NULL;
    json_object_object_get_ex(o, key, &v);
    return v;
}
static const char *str(json_object *o, const char *key) {
    const char *s = json_object_get_string(field(o, key));
    return s ? s : "";
}
static void copy(char *out, size_t size, const char *in) {
    if (strlen(in) >= size) { fprintf(stderr, "Configuration/path too long\n"); exit(1); }
    memcpy(out, in, strlen(in) + 1);
}
static void path_join(char *out, size_t size, const char *a, const char *b) {
    if (snprintf(out, size, "%s/%s", a, b) >= (int)size) { fprintf(stderr, "Path too long\n"); exit(1); }
}
static bool valid_id(const char *s) {
    if (!*s || strlen(s) > 64) return false;
    for (; *s; ++s) if (!((*s >= 'a' && *s <= 'z') || (*s >= 'A' && *s <= 'Z') ||
                          (*s >= '0' && *s <= '9') || *s == '_' || *s == '-')) return false;
    return true;
}
static void add_s(json_object *o, const char *key, const char *value) {
    json_object_object_add(o, key, json_object_new_string(value));
}
static void add_d(json_object *o, const char *key, double value) {
    json_object_object_add(o, key, json_object_new_double(value));
}
static void make_dir(const char *path) { if (mkdir(path, 0700) && errno != EEXIST) die(path); }

static void bind_device_port(Device *device) {
    if (simulate || !strncmp(device->configured_port, "/dev/serial/by-id/", 18)) return;
    json_object *cached = field(port_cache, device->id);
    if (cached && !strcmp(str(cached, "configured_port"), device->configured_port)
            && *str(cached, "stable_port")) {
        copy(device->port, sizeof(device->port), str(cached, "stable_port"));
        return;
    }
    char resolved[PATH_SIZE];
    if (!realpath(device->configured_port, resolved)) return;
    const char *directory = getenv("CSI_SERIAL_BY_ID_DIR");
    if (!directory) directory = "/dev/serial/by-id";
    DIR *dir = opendir(directory);
    if (!dir) return;
    char best[PATH_SIZE] = "";
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (entry->d_name[0] == '.') continue;
        char candidate[PATH_SIZE], target[PATH_SIZE];
        path_join(candidate, sizeof(candidate), directory, entry->d_name);
        if (realpath(candidate, target) && !strcmp(target, resolved)
                && (!*best || strcmp(candidate, best) < 0)) copy(best, sizeof(best), candidate);
    }
    closedir(dir);
    if (!*best) return;
    copy(device->port, sizeof(device->port), best);
    json_object *binding = json_object_new_object();
    add_s(binding, "configured_port", device->configured_port);
    add_s(binding, "stable_port", best);
    json_object_object_add(port_cache, device->id, binding);
    char temporary[PATH_SIZE];
    if (snprintf(temporary, sizeof(temporary), "%s.tmp", port_cache_path) >= (int)sizeof(temporary)) die("Cache path");
    if (json_object_to_file_ext(temporary, port_cache, JSON_C_TO_STRING_PRETTY) || rename(temporary, port_cache_path))
        fprintf(stderr, "Warning: could not persist USB binding cache\n");
    fprintf(stderr, "USB %s: %s -> %s\n", device->id, device->configured_port, device->port);
}

static char *trim(char *value) {
    while (isspace((unsigned char)*value)) value++;
    size_t length = strlen(value);
    while (length && isspace((unsigned char)value[length - 1])) value[--length] = 0;
    return value;
}
static bool valid_token(const char *value) {
    if (!*value || strlen(value) > 255) return false;
    for (; *value; value++) if (!((*value >= 'a' && *value <= 'z') ||
            (*value >= 'A' && *value <= 'Z') || (*value >= '0' && *value <= '9') ||
            *value == '.' || *value == '_' || *value == '~' || *value == '-')) return false;
    return true;
}
static void load_token_env(void) {
    if (getenv("CSI_TOKEN")) return;
    const char *explicit_path = getenv("CSI_ENV_FILE");
    char path[PATH_SIZE];
    if (explicit_path) copy(path, sizeof(path), explicit_path);
    else {
        char executable[PATH_SIZE];
        ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
        if (length < 0 || (size_t)length >= sizeof(executable) - 1) die("Locate .env");
        executable[length] = 0;
        char *slash = strrchr(executable, '/');
        if (!slash) die("Locate agent directory");
        *slash = 0;
        slash = strrchr(executable, '/');
        if (!slash) die("Locate project directory");
        *slash = 0;
        path_join(path, sizeof(path), executable, ".env");
    }
    FILE *input = fopen(path, "r");
    if (!input) {
        if (!explicit_path && errno == ENOENT) return; /* Legacy JSON token remains supported. */
        die("Read CSI_ENV_FILE");
    }
    char *line = NULL;
    size_t capacity = 0;
    while (getline(&line, &capacity, input) >= 0) {
        char *key = trim(line);
        if (!strncmp(key, "export ", 7)) key = trim(key + 7);
        char *equals = strchr(key, '=');
        if (!equals) continue;
        *equals = 0;
        if (strcmp(trim(key), "CSI_TOKEN")) continue;
        char *value = trim(equals + 1);
        if (*value == '\'' || *value == '"') {
            char quote = *value++;
            char *closing = strchr(value, quote);
            if (!closing || (*trim(closing + 1) && *trim(closing + 1) != '#')) {
                fprintf(stderr, "Invalid CSI_TOKEN quoting in .env\n"); exit(1);
            }
            *closing = 0;
        } else {
            char *comment = strchr(value, '#');
            if (comment) *comment = 0;
            value = trim(value);
        }
        if (!valid_token(value)) { fprintf(stderr, "Invalid CSI_TOKEN in .env\n"); exit(1); }
        if (setenv("CSI_TOKEN", value, 0)) die("Set CSI_TOKEN");
        break;
    }
    free(line);
    fclose(input);
}

typedef struct { char *data; size_t size; } Response;
static size_t receive(void *ptr, size_t size, size_t n, void *user) {
    Response *r = user;
    size_t count = size * n;
    if (r->size + count > 512 * 1024) return 0;
    char *next = realloc(r->data, r->size + count + 1);
    if (!next) return 0;
    r->data = next;
    memcpy(r->data + r->size, ptr, count);
    r->size += count;
    r->data[r->size] = 0;
    return count;
}
static json_object *request(const char *route, json_object *payload, const char *file,
                            double *midpoint, double *rtt) {
    CURL *curl = curl_easy_init();
    if (!curl) return NULL;
    char url[2048], auth[300];
    snprintf(url, sizeof(url), "%s%s", server_url, route);
    snprintf(auth, sizeof(auth), "Authorization: Bearer %s", token);
    struct curl_slist *headers = curl_slist_append(NULL, auth);
    headers = curl_slist_append(headers, "Expect:");
    headers = curl_slist_append(headers, file ? "Content-Type: text/csv" : "Content-Type: application/json");
    Response response = {0};
    FILE *input = NULL;
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 1500L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, file ? 120000L : 3000L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, receive);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    if (file) {
        struct stat st;
        input = fopen(file, "rb");
        if (!input || fstat(fileno(input), &st)) goto cleanup;
        curl_easy_setopt(curl, CURLOPT_UPLOAD, 1L);
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "POST");
        curl_easy_setopt(curl, CURLOPT_READDATA, input);
        curl_easy_setopt(curl, CURLOPT_INFILESIZE_LARGE, (curl_off_t)st.st_size);
    } else {
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_object_to_json_string_ext(payload, JSON_C_TO_STRING_PLAIN));
    }
    double before = mono();
    CURLcode rc = curl_easy_perform(curl);
    double after = mono();
    if (midpoint) *midpoint = (before + after) / 2;
    if (rtt) *rtt = after - before;
    long code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
    if (rc != CURLE_OK || code != 200) {
        fprintf(stderr, "HTTP %s: %s, status %ld%s%s\n", route, curl_easy_strerror(rc), code,
                response.data ? ": " : "", response.data ? response.data : "");
        free(response.data);
        response.data = NULL;
    }
cleanup:
    if (input) fclose(input);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    json_object *result = response.data ? json_tokener_parse(response.data) : NULL;
    free(response.data);
    return result;
}

static speed_t baud_speed(int baud) {
    switch (baud) {
        case 9600: return B9600;
        case 57600: return B57600;
        case 115200: return B115200;
        case 230400: return B230400;
        case 460800: return B460800;
        case 921600: return B921600;
        default: return 0;
    }
}
static int open_serial(Device *device) {
    speed_t speed = baud_speed(device->baud);
    if (!speed) { errno = EINVAL; return -1; }
    int fd = open(device->port, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) return -1;
    struct termios options;
    if (tcgetattr(fd, &options)) { close(fd); return -1; }
    cfmakeraw(&options);
    options.c_cflag |= CLOCAL | CREAD;
    options.c_cflag &= ~CRTSCTS;
    cfsetispeed(&options, speed);
    cfsetospeed(&options, speed);
    if (tcsetattr(fd, TCSANOW, &options)) { close(fd); return -1; }
    tcflush(fd, TCIFLUSH);
    return fd;
}
/* Parse just enough of both supported firmware CSV formats to count valid CSI.
 * Boot messages, invalid IQ arrays and other transmitters never consume quota. */
static int csv_fields(char *line, char **fields, int maximum) {
    char *read = line, *write = line;
    int count = 0;
    for (;;) {
        if (count == maximum) return -1;
        fields[count++] = write;
        if (*read == '"') {
            read++;
            for (;;) {
                if (!*read) return -1;
                if (*read == '"') {
                    if (read[1] == '"') { *write++ = '"'; read += 2; }
                    else { read++; break; }
                } else *write++ = *read++;
            }
            while (*read == ' ' || *read == '\r') read++;
            if (*read && *read != ',') return -1;
        } else while (*read && *read != ',') *write++ = *read++;
        bool more = *read == ',';
        if (more) read++;
        *write++ = 0;
        if (!more) return count;
    }
}
static bool number(const char *value, double *out) {
    char *end;
    errno = 0;
    *out = strtod(value, &end);
    while (isspace((unsigned char)*end)) end++;
    return end != value && !*end && !errno && isfinite(*out);
}
static bool integer(const char *value, double *out) {
    char *end;
    errno = 0;
    long long parsed = strtoll(value, &end, 10);
    while (isspace((unsigned char)*end)) end++;
    if (end == value || *end || errno) return false;
    *out = (double)parsed;
    return true;
}
static bool valid_packet(Reader *r, const char *line) {
    char scratch[LINE_SIZE], *fields[32];
    copy(scratch, sizeof(scratch), line);
    int count = csv_fields(scratch, fields, 32);
    const char *timestamp, *data, *rssi, *mac, *first, *length;
    if (count == 6) {
        timestamp=fields[0]; data=fields[1]; rssi=fields[2]; mac=fields[3]; first=fields[4]; length=fields[5];
    } else if (count == 25 && !strcmp(fields[0], "CSI_DATA")) {
        timestamp=fields[18]; data=fields[24]; rssi=fields[3]; mac=fields[2]; first=fields[23]; length=fields[22];
    } else return false;
    double local, signal, invalid, size;
    if (!integer(timestamp, &local) || local < 0 || local >= 4294967296.0
            || !number(rssi, &signal) || !integer(first, &invalid) || (invalid != 0 && invalid != 1)
            || !integer(length, &size) || size < 128 || size > 4096) return false;
    if (strlen(mac) != 17) return false;
    char normalized_mac[18];
    for (int i = 0; i < 17; i++) {
        if (i % 3 == 2 ? mac[i] != ':' : !isxdigit((unsigned char)mac[i])) return false;
        normalized_mac[i] = (char)tolower((unsigned char)mac[i]);
    }
    normalized_mac[17] = 0;
    if (*r->selected_mac && strcmp(r->selected_mac, normalized_mac)) return false;
    struct json_tokener *tokener = json_tokener_new();
    json_object *iq = json_tokener_parse_ex(tokener, data, (int)strlen(data));
    bool ok = json_tokener_get_error(tokener) == json_tokener_success
              && iq && json_object_is_type(iq, json_type_array)
              && json_object_array_length(iq) == (size_t)size;
    const char *tail = data + json_tokener_get_parse_end(tokener);
    while (isspace((unsigned char)*tail)) tail++;
    if (*tail) ok = false;
    json_tokener_free(tokener);
    bool nonzero = false;
    if (ok) for (int i = 0; i < (int)size; i++) {
        json_object *value = json_object_array_get_idx(iq, (size_t)i);
        int v = json_object_get_int(value);
        if (!json_object_is_type(value, json_type_int) || v < -128 || v > 127) { ok=false; break; }
        int carrier = i / 2;
        if ((carrier >= 38 && carrier <= 63) || (carrier >= (invalid ? 2 : 1) && carrier <= 26))
            if (v) nonzero = true;
    }
    json_object_put(iq);
    if (!ok || !nonzero) return false;
    if (!*r->selected_mac) copy(r->selected_mac, sizeof(r->selected_mac), normalized_mac);
    return true;
}
static void write_line(Reader *r, const char *line, double now) {
    double start = atomic_load(&start_mono), end = atomic_load(&end_mono);
    if (start <= 0 || now < start || now >= end || !strchr(line, '[')) return;
    if (sample_mode && atomic_load(&r->rows) >= packet_target) return;
    if (sample_mode && !valid_packet(r, line)) { r->rejected++; return; }
    double stamp = now + epoch_offset;
    fprintf(r->output, "%.6f,\"", stamp);
    for (const char *p = line; *p; p++) {
        if (*p == '"') fputc('"', r->output);
        if (*p != '\r') fputc(*p, r->output);
    }
    fputs("\"\n", r->output);
    if (ferror(r->output) || ftell(r->output) > FILE_LIMIT) {
        copy(r->error, sizeof(r->error), "Disk write failed or per-device 48 MiB limit reached");
        return;
    }
    if (!r->rows) r->first = stamp;
    r->last = stamp;
    r->rows++;
    r->last_packet = now;
}
static void simulated_line(Reader *r, char *line, size_t size, double now) {
    unsigned long tick = (unsigned long)(now * 1e6) & 0xffffffffUL;
    size_t used = (size_t)snprintf(line, size, "%lu,\"[", tick);
    for (int k = 0; k < 64; k++) {
        double t = now - atomic_load(&start_mono);
        int real = (int)(30 + 12 * sin(k * .25 + t * (1.5 + r->index * .17)));
        used += (size_t)snprintf(line + used, size - used, "%s%d,%d", k ? "," : "", 4 + k % 6, real);
    }
    snprintf(line + used, size - used, "]\",-45,aa:bb:cc:dd:ee:ff,0,128");
}
static void *reader_main(void *user) {
    Reader *r = user;
    char line[LINE_SIZE], buffer[4096];
    size_t used = 0;
    bool overflow = false;
    double last_flush = mono();
    while (!atomic_load(&stop_readers)) {
        double now = mono(), end = atomic_load(&end_mono);
        double start = atomic_load(&start_mono);
        if (sample_mode && atomic_load(&r->rows) >= packet_target) break;
        if (end > 0 && now >= end) {
            if (sample_mode) copy(r->error, sizeof(r->error), "Sample target not reached before failure timeout");
            break;
        }
        if (sample_mode && start > 0 && now > start
                && now - fmax(start, r->last_packet) >= idle_timeout) {
            copy(r->error, sizeof(r->error), "No valid CSI packets within idle timeout");
            break;
        }
        if (simulate) {
            simulated_line(r, line, sizeof(line), now);
            write_line(r, line, now);
            pause_ms(40);
        } else {
            ssize_t n = read(r->fd, buffer, sizeof(buffer));
            if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                snprintf(r->error, sizeof(r->error), "USB read: %s", strerror(errno));
                break;
            }
            if (n <= 0) pause_ms(2);
            for (ssize_t i = 0; i < n; i++) {
                if (buffer[i] == '\n') {
                    line[used] = 0;
                    if (!overflow) write_line(r, line, mono());
                    used = 0;
                    overflow = false;
                } else if (used + 1 < sizeof(line)) line[used++] = buffer[i];
                else overflow = true;
            }
        }
        if (r->error[0]) break;
        if (mono() - last_flush > 1) {
            if (fflush(r->output)) { copy(r->error, sizeof(r->error), "Disk flush failed"); break; }
            last_flush = mono();
        }
    }
    atomic_store(&r->finished, true);
    return NULL;
}

static json_object *heartbeat_payload(bool pending) {
    json_object *o = json_object_new_object(), *list = json_object_new_array();
    add_s(o, "pi_id", pi_id);
    add_s(o, "job_id", active_job);
    add_d(o, "capture_protocol", 2);
    json_object_object_add(o, "busy", json_object_new_boolean(pending || active_job[0]));
    for (int i = 0; i < device_count; i++) {
        json_object *d = json_object_new_object();
        add_s(d, "id", devices[i].id);
        add_s(d, "port", devices[i].port);
        add_s(d, "configured_port", devices[i].configured_port);
        add_s(d, "target_mac", devices[i].mac);
        add_d(d, "baud", devices[i].baud);
        json_object_object_add(d, "simulated", json_object_new_boolean(simulate));
        json_object_array_add(list, d);
    }
    json_object_object_add(o, "devices", list);
    if (*active_job && sample_mode) {
        json_object *progress = json_object_new_object(), *items = json_object_new_object();
        add_s(progress, "job_id", active_job);
        for (int i = 0; i < reader_count; i++) {
            json_object *state = json_object_new_object();
            add_d(state, "captured", (double)atomic_load(&readers[i].rows));
            json_object_object_add(state, "finished", json_object_new_boolean(atomic_load(&readers[i].finished)));
            json_object_object_add(items, readers[i].device.id, state);
        }
        json_object_object_add(progress, "devices", items);
        json_object_object_add(o, "progress", progress);
    }
    return o;
}
static void prepare(json_object *command, double offset) {
    copy(active_job, sizeof(active_job), str(command, "id"));
    path_join(active_dir, sizeof(active_dir), spool, active_job);
    make_dir(active_dir);
    epoch_offset = offset;
    sample_mode = !strcmp(str(command, "capture_mode"), "samples");
    packet_target = (unsigned long)json_object_get_int64(field(command, "capture_count"));
    idle_timeout = json_object_get_double(field(command, "idle_timeout_seconds"));
    atomic_store(&start_mono, 0);
    atomic_store(&end_mono, 0);
    atomic_store(&stop_readers, false);
    reader_count = 0;
    ready_sent = false;
    prepare_error[0] = 0;
    json_object *list = field(command, "devices");
    size_t count = json_object_array_length(list);
    if (count > MAX_DEVICES) { copy(prepare_error, sizeof(prepare_error), "Too many devices"); return; }
    for (size_t i = 0; i < count; i++) {
        const char *id = str(json_object_array_get_idx(list, i), "id");
        Device *device = NULL;
        for (int j = 0; j < device_count; j++) if (!strcmp(devices[j].id, id)) device = &devices[j];
        if (!device) { copy(prepare_error, sizeof(prepare_error), "Unknown selected device"); break; }
        Reader *r = &readers[reader_count++];
        memset(r, 0, sizeof(*r));
        atomic_init(&r->rows, 0);
        atomic_init(&r->finished, false);
        r->device = *device;
        copy(r->selected_mac, sizeof(r->selected_mac), device->mac);
        for (char *p=r->selected_mac; *p; p++) *p=(char)tolower((unsigned char)*p);
        r->index = (int)i + (pi_id[strlen(pi_id) - 1] % 5) * 2;
        r->fd = -1;
        char filename[80], path[PATH_SIZE];
        snprintf(filename, sizeof(filename), "%s.raw.csv", device->id);
        path_join(path, sizeof(path), active_dir, filename);
        r->output = fopen(path, "wb");
        if (!r->output) {
            copy(r->error, sizeof(r->error), "Cannot open spool file");
            copy(prepare_error, sizeof(prepare_error), r->error);
            fprintf(stderr, "%s (%s)\n", r->error, device->port);
            continue;
        }
        fputs("host_timestamp,raw_line\n", r->output);
        if (!simulate) r->fd = open_serial(device);
        if (!simulate && r->fd < 0) {
            snprintf(r->error, sizeof(r->error), "Open %s: %.120s", device->id, strerror(errno));
            copy(prepare_error, sizeof(prepare_error), r->error);
            continue;
        }
        int rc = pthread_create(&r->thread, NULL, reader_main, r);
        if (rc) {
            copy(r->error, sizeof(r->error), "Cannot create reader thread");
            copy(prepare_error, sizeof(prepare_error), r->error);
            continue;
        }
        r->launched = true;
    }
    fprintf(stderr, "%s %s (%d ESP32)%s%s\n", *prepare_error ? "Preparation failed" : "Prepared",
            active_job, reader_count, *prepare_error ? ": " : "", prepare_error);
}
static void send_ready(void) {
    json_object *o = json_object_new_object();
    add_s(o, "pi_id", pi_id);
    add_s(o, "job_id", active_job);
    add_s(o, "error", prepare_error);
    add_d(o, "clock_rtt_seconds", last_rtt);
    json_object *reply = request("/api/ready", o, NULL, NULL, NULL);
    if (reply) ready_sent = true;
    json_object_put(reply);
    json_object_put(o);
}
static void finish(const char *error) {
    atomic_store(&stop_readers, true);
    json_object *report = json_object_new_object(), *items = json_object_new_object();
    add_s(report, "job_id", active_job);
    add_s(report, "pi_id", pi_id);
    add_d(report, "clock_rtt_seconds", last_rtt);
    for (int i = 0; i < reader_count; i++) {
        Reader *r = &readers[i];
        if (r->launched) pthread_join(r->thread, NULL);
        if (r->fd >= 0) close(r->fd);
        if (r->output) {
            if (fflush(r->output) || fsync(fileno(r->output)))
                copy(r->error, sizeof(r->error), "Final disk flush failed");
            if (fclose(r->output)) copy(r->error, sizeof(r->error), "File close failed");
        }
        json_object *d = json_object_new_object();
        add_d(d, "raw_rows", (double)r->rows);
        add_d(d, "rejected_rows", (double)r->rejected);
        add_s(d, "target_mac", r->selected_mac);
        add_d(d, "first_host_timestamp", r->first);
        add_d(d, "last_host_timestamp", r->last);
        add_s(d, "error", r->error[0] ? r->error : error);
        json_object_object_add(items, r->device.id, d);
    }
    json_object_object_add(report, "devices", items);
    char tmp[PATH_SIZE], final[PATH_SIZE];
    path_join(tmp, sizeof(tmp), active_dir, "result.json.tmp");
    path_join(final, sizeof(final), active_dir, "result.json");
    if (json_object_to_file_ext(tmp, report, JSON_C_TO_STRING_PRETTY)) die("Save result manifest");
    int manifest_fd = open(tmp, O_RDONLY);
    if (manifest_fd < 0 || fsync(manifest_fd)) die("Sync result manifest");
    close(manifest_fd);
    if (rename(tmp, final)) die("Commit result manifest");
    int directory_fd = open(active_dir, O_RDONLY | O_DIRECTORY);
    if (directory_fd < 0 || fsync(directory_fd)) die("Sync session directory");
    close(directory_fd);
    json_object_put(report);
    fprintf(stderr, "Saved session %s; automatic upload queued\n", active_job);
    active_job[0] = 0;
    reader_count = 0;
}
/* Completed manifests survive process/network restarts. Uploads are idempotent. */
static bool upload_pending(void) {
    DIR *dir = opendir(spool);
    if (!dir) die("Open spool");
    bool pending = false;
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (!valid_id(entry->d_name) || !strcmp(entry->d_name, active_job)) continue;
        char folder[PATH_SIZE], manifest[PATH_SIZE], marker[PATH_SIZE];
        path_join(folder, sizeof(folder), spool, entry->d_name);
        path_join(manifest, sizeof(manifest), folder, "result.json");
        path_join(marker, sizeof(marker), folder, "uploaded");
        if (access(marker, F_OK) == 0 || access(manifest, F_OK)) continue;
        json_object *report = json_object_from_file(manifest);
        if (!report) { pending = true; continue; }
        bool ok = true;
        json_object *items = field(report, "devices");
        json_object_object_foreach(items, id, value) {
            (void)value;
            char route[256], filename[80], path[PATH_SIZE];
            snprintf(route, sizeof(route), "/api/upload/%s/%s/%s", entry->d_name, pi_id, id);
            snprintf(filename, sizeof(filename), "%s.raw.csv", id);
            path_join(path, sizeof(path), folder, filename);
            if (access(path, F_OK) && *str(value, "error")) continue;
            json_object *reply = request(route, NULL, path, NULL, NULL);
            if (!reply) ok = false;
            json_object_put(reply);
            if (!ok) break;
        }
        if (ok) {
            json_object *reply = request("/api/complete", report, NULL, NULL, NULL);
            ok = reply != NULL;
            json_object_put(reply);
        }
        if (ok) {
            FILE *f = fopen(marker, "w");
            if (f) { fputs("uploaded\n", f); fclose(f); }
            fprintf(stderr, "Uploaded %s\n", entry->d_name);
        } else pending = true;
        json_object_put(report);
        if (quitting) break;
    }
    closedir(dir);
    return pending;
}
static void configure(const char *path) {
    json_object *config = json_object_from_file(path);
    if (!config) { fprintf(stderr, "Cannot read configuration: %s\n", path); exit(1); }
    copy(server_url, sizeof(server_url), str(config, "server"));
    size_t n = strlen(server_url);
    while (n && server_url[n - 1] == '/') server_url[--n] = 0;
    copy(pi_id, sizeof(pi_id), str(config, "pi_id"));
    copy(token, sizeof(token), getenv("CSI_TOKEN") ? getenv("CSI_TOKEN") : str(config, "token"));
    copy(spool, sizeof(spool), str(config, "spool_dir"));
    if (!*spool) snprintf(spool, sizeof(spool), "spool-%s", pi_id);
    if (!valid_id(pi_id) || !valid_token(token) || (strncmp(server_url, "http://", 7) && strncmp(server_url, "https://", 8))) {
        fprintf(stderr, "Provide valid pi_id, server URL and CSI_TOKEN in project .env (or environment/legacy JSON)\n"); exit(1);
    }
    json_object *list = field(config, "devices");
    device_count = (int)json_object_array_length(list);
    if (device_count < 1 || device_count > MAX_DEVICES) { fprintf(stderr, "Configure 1–64 devices\n"); exit(1); }
    if (snprintf(port_cache_path, sizeof(port_cache_path), "%s.ports.json", path) >= (int)sizeof(port_cache_path)) die("Port cache path");
    port_cache = json_object_from_file(port_cache_path);
    if (!port_cache || !json_object_is_type(port_cache, json_type_object)) {
        json_object_put(port_cache);
        port_cache = json_object_new_object();
    }
    for (int i = 0; i < device_count; i++) {
        json_object *d = json_object_array_get_idx(list, (size_t)i);
        copy(devices[i].id, sizeof(devices[i].id), str(d, "id"));
        copy(devices[i].port, sizeof(devices[i].port), str(d, "port"));
        copy(devices[i].configured_port, sizeof(devices[i].configured_port), str(d, "port"));
        bind_device_port(&devices[i]);
        copy(devices[i].mac, sizeof(devices[i].mac), str(d, "target_mac"));
        devices[i].baud = field(d, "baud") ? json_object_get_int(field(d, "baud")) : 115200;
        if (!valid_id(devices[i].id) || (!simulate && (!*devices[i].port || !baud_speed(devices[i].baud)))) {
            fprintf(stderr, "Invalid device configuration\n"); exit(1);
        }
        for (int j = 0; j < i; j++) if (!strcmp(devices[i].id, devices[j].id) ||
                (!simulate && !strcmp(devices[i].port, devices[j].port))) {
            fprintf(stderr, "Duplicate device ID or serial port\n"); exit(1);
        }
    }
    json_object_put(config);
    make_dir(spool);
    char lock_path[PATH_SIZE];
    path_join(lock_path, sizeof(lock_path), spool, ".agent.lock");
    spool_lock = open(lock_path, O_CREAT | O_RDWR, 0600);
    if (spool_lock < 0 || flock(spool_lock, LOCK_EX | LOCK_NB)) die("Spool already in use or inaccessible");
}
int main(int argc, char **argv) {
    if (argc < 2 || argc > 3 || (argc == 3 && strcmp(argv[2], "--simulate"))) {
        fprintf(stderr, "Usage: %s CONFIG.json [--simulate]\n", argv[0]); return 2;
    }
    simulate = argc == 3;
    load_token_env();
    configure(argv[1]);
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    curl_global_init(CURL_GLOBAL_DEFAULT);
    double next_retry = 0, prepared_at = 0;
    bool pending = false;
    fprintf(stderr, "%s: %d ESP32, %s mode\n", pi_id, device_count, simulate ? "SIMULATED" : "USB");
    while (!quitting) {
        if (!active_job[0] && mono() >= next_retry) {
            pending = upload_pending();
            next_retry = mono() + 3;
        }
        if (!active_job[0]) for (int i=0; i<device_count; i++) bind_device_port(&devices[i]);
        json_object *payload = heartbeat_payload(pending);
        double midpoint = 0, rtt = 0;
        json_object *reply = request("/api/heartbeat", payload, NULL, &midpoint, &rtt);
        json_object_put(payload);
        if (reply) {
            json_object *command = field(reply, "command");
            const char *state = str(command, "status");
            if (!active_job[0] && !pending && !strcmp(state, "preparing") && valid_id(str(command, "id"))) {
                last_rtt = rtt;
                prepare(command, json_object_get_double(field(reply, "server_time")) - midpoint);
                prepared_at = mono();
            }
            if (active_job[0] && !strcmp(active_job, str(command, "id"))) {
                if (!strcmp(state, "preparing") && !ready_sent) send_ready();
                if ((!strcmp(state, "waiting") || !strcmp(state, "collecting")) && atomic_load(&start_mono) == 0) {
                    double start = json_object_get_double(field(command, "start_at")) - epoch_offset;
                    double end = json_object_get_double(field(command, "end_at")) - epoch_offset;
                    if (mono() > start + .25) finish("Start command arrived late; collection aborted");
                    else {
                        atomic_store(&end_mono, end);
                        atomic_store(&start_mono, start);
                        fprintf(stderr, "Scheduled start in %.3f seconds\n", start - mono());
                    }
                } else if (strcmp(state, "preparing") && strcmp(state, "waiting") &&
                           strcmp(state, "collecting") && strcmp(state, "uploading")) {
                    finish("Session cancelled or failed");
                    next_retry = 0;
                }
            }
            json_object_put(reply);
        }
        if (active_job[0]) {
            double end = atomic_load(&end_mono);
            bool all_finished = reader_count > 0;
            for (int i=0; i<reader_count; i++) if (readers[i].launched && !atomic_load(&readers[i].finished)) all_finished=false;
            if (sample_mode && end > 0 && all_finished) { finish(""); next_retry = 0; }
            else if (end > 0 && mono() >= end) { finish(sample_mode ? "Capture failure timeout" : ""); next_retry = 0; }
            else if (end == 0 && mono() - prepared_at > 35) { finish("Preparation timed out"); next_retry = 0; }
        }
        pause_ms(200);
    }
    if (active_job[0]) finish("Agent stopped by signal");
    curl_global_cleanup();
    close(spool_lock);
    json_object_put(port_cache);
    return 0;
}
