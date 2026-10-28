CC ?= cc
CFLAGS ?= -O2 -g -std=c11 -Wall -Wextra -Wpedantic
CPPFLAGS += $(shell pkg-config --cflags libcurl json-c)
LDLIBS += $(shell pkg-config --libs libcurl json-c) -lpthread -lm -latomic

all: csi-agent
csi-agent: agent.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f csi-agent
# Rebuild on this machine even when a binary was copied from another CPU.
.PHONY: all clean csi-agent
