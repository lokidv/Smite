#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/epoll.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define MAX_CLIENTS 2048
#define BUFFER_SIZE 65535
#define CLIENT_TIMEOUT 600
#define SOCK_BUF_SIZE (4 * 1024 * 1024)

typedef struct {
    struct sockaddr_in client_addr;
    struct sockaddr_in orig_dst;
    int backend_fd;
    time_t last_active;
    int in_use;
} ClientSession;

static ClientSession sessions[MAX_CLIENTS];
static int listen_fd = -1;
static int epoll_fd = -1;
static struct sockaddr_in target_addr;
static volatile int running = 1;

static void handle_signal(int sig) {
    (void)sig;
    running = 0;
}

static int find_or_create_session(const struct sockaddr_in *client_addr, const struct sockaddr_in *orig_dst) {
    time_t now = time(NULL);
    int oldest_idx = -1;
    time_t oldest_time = now;

    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (sessions[i].in_use) {
            if (sessions[i].client_addr.sin_addr.s_addr == client_addr->sin_addr.s_addr &&
                sessions[i].client_addr.sin_port == client_addr->sin_port) {
                sessions[i].last_active = now;
                return i;
            }
            if (now - sessions[i].last_active > CLIENT_TIMEOUT) {
                if (sessions[i].backend_fd >= 0) {
                    epoll_ctl(epoll_fd, EPOLL_CTL_DEL, sessions[i].backend_fd, NULL);
                    close(sessions[i].backend_fd);
                }
                sessions[i].in_use = 0;
            } else if (sessions[i].last_active < oldest_time) {
                oldest_time = sessions[i].last_active;
                oldest_idx = i;
            }
        }
    }

    int slot = -1;
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (!sessions[i].in_use) {
            slot = i;
            break;
        }
    }
    if (slot == -1) {
        slot = oldest_idx;
        if (slot >= 0 && sessions[slot].in_use) {
            if (sessions[slot].backend_fd >= 0) {
                epoll_ctl(epoll_fd, EPOLL_CTL_DEL, sessions[slot].backend_fd, NULL);
                close(sessions[slot].backend_fd);
            }
            sessions[slot].in_use = 0;
        }
    }
    if (slot == -1) return -1;

    int bfd = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, 0);
    if (bfd < 0) return -1;

    int opt = 1;
    setsockopt(bfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#ifdef SO_REUSEPORT
    setsockopt(bfd, SOL_SOCKET, SO_REUSEPORT, &opt, sizeof(opt));
#endif
    int buf_size = SOCK_BUF_SIZE;
    setsockopt(bfd, SOL_SOCKET, SO_RCVBUF, &buf_size, sizeof(buf_size));
    setsockopt(bfd, SOL_SOCKET, SO_SNDBUF, &buf_size, sizeof(buf_size));

    if (connect(bfd, (struct sockaddr *)&target_addr, sizeof(target_addr)) < 0) {
        close(bfd);
        return -1;
    }

    struct epoll_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.events = EPOLLIN | EPOLLERR | EPOLLHUP;
    ev.data.u32 = slot;
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, bfd, &ev) < 0) {
        close(bfd);
        return -1;
    }

    sessions[slot].client_addr = *client_addr;
    if (orig_dst) sessions[slot].orig_dst = *orig_dst;
    sessions[slot].backend_fd = bfd;
    sessions[slot].last_active = now;
    sessions[slot].in_use = 1;
    return slot;
}

int main(int argc, char *argv[]) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <listen_port> <target_ip> <target_port>\n", argv[0]);
        return 1;
    }
    int listen_port = atoi(argv[1]);
    const char *target_ip = argv[2];
    int target_port = atoi(argv[3]);

    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    signal(SIGPIPE, SIG_IGN);
    signal(SIGHUP, SIG_IGN);

    memset(&target_addr, 0, sizeof(target_addr));
    target_addr.sin_family = AF_INET;
    target_addr.sin_port = htons(target_port);
    if (inet_pton(AF_INET, target_ip, &target_addr.sin_addr) <= 0) {
        fprintf(stderr, "Invalid target IP: %s\n", target_ip);
        return 1;
    }

    listen_fd = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, 0);
    if (listen_fd < 0) { perror("socket"); return 1; }

    int opt = 1;
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#ifdef SO_REUSEPORT
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEPORT, &opt, sizeof(opt));
#endif
    setsockopt(listen_fd, SOL_IP, IP_PKTINFO, &opt, sizeof(opt));

    int buf_size = SOCK_BUF_SIZE;
    setsockopt(listen_fd, SOL_SOCKET, SO_RCVBUF, &buf_size, sizeof(buf_size));
    setsockopt(listen_fd, SOL_SOCKET, SO_SNDBUF, &buf_size, sizeof(buf_size));

    struct sockaddr_in listen_addr;
    memset(&listen_addr, 0, sizeof(listen_addr));
    listen_addr.sin_family = AF_INET;
    listen_addr.sin_addr.s_addr = INADDR_ANY;
    listen_addr.sin_port = htons(listen_port);

    int bound = 0;
    for (int attempt = 0; attempt < 15; attempt++) {
        if (bind(listen_fd, (struct sockaddr *)&listen_addr, sizeof(listen_addr)) == 0) {
            bound = 1;
            break;
        }
        if (errno != EADDRINUSE) {
            break;
        }
        usleep(100000); // 100ms
    }

    if (!bound) {
        perror("bind");
        close(listen_fd);
        return 1;
    }

    epoll_fd = epoll_create1(0);
    if (epoll_fd < 0) { perror("epoll_create1"); close(listen_fd); return 1; }

    struct epoll_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.events = EPOLLIN | EPOLLERR | EPOLLHUP;
    ev.data.u32 = 0xFFFFFFFF; // Marker for listen_fd
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, listen_fd, &ev) < 0) {
        perror("epoll_ctl listen_fd");
        close(epoll_fd);
        close(listen_fd);
        return 1;
    }

    struct epoll_event events[64];
    uint8_t buffer[BUFFER_SIZE];

    printf("smite-udp-relay started: listen %d -> %s:%d\n", listen_port, target_ip, target_port);
    fflush(stdout);

    while (running) {
        int n = epoll_wait(epoll_fd, events, 64, 2000);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }

        time_t now = time(NULL);
        for (int i = 0; i < n; i++) {
            uint32_t marker = events[i].data.u32;
            if (marker == 0xFFFFFFFF) {
                // Inbound packet from client on listen_fd
                if (events[i].events & (EPOLLERR | EPOLLHUP)) {
                    continue;
                }
                while (1) {
                    struct sockaddr_in client_addr;
                    struct msghdr msg;
                    struct iovec iov;
                    uint8_t cbuf[256];

                    iov.iov_base = buffer;
                    iov.iov_len = sizeof(buffer);
                    memset(&msg, 0, sizeof(msg));
                    msg.msg_name = &client_addr;
                    msg.msg_namelen = sizeof(client_addr);
                    msg.msg_iov = &iov;
                    msg.msg_iovlen = 1;
                    msg.msg_control = cbuf;
                    msg.msg_controllen = sizeof(cbuf);

                    ssize_t len = recvmsg(listen_fd, &msg, MSG_DONTWAIT);
                    if (len <= 0) break;

                    struct sockaddr_in orig_dst;
                    memset(&orig_dst, 0, sizeof(orig_dst));
                    for (struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg); cmsg != NULL; cmsg = CMSG_NXTHDR(&msg, cmsg)) {
                        if (cmsg->cmsg_level == SOL_IP && cmsg->cmsg_type == IP_PKTINFO) {
                            struct in_pktinfo *pi = (struct in_pktinfo *)CMSG_DATA(cmsg);
                            orig_dst.sin_family = AF_INET;
                            orig_dst.sin_addr = pi->ipi_spec_dst;
                        }
                    }

                    int slot = find_or_create_session(&client_addr, &orig_dst);
                    if (slot >= 0 && sessions[slot].backend_fd >= 0) {
                        send(sessions[slot].backend_fd, buffer, len, MSG_NOSIGNAL);
                    }
                }
            } else {
                // Outbound packet from backend back to client
                uint32_t slot = marker;
                if (slot < MAX_CLIENTS && sessions[slot].in_use) {
                    if (events[i].events & (EPOLLERR | EPOLLHUP)) {
                        if (sessions[slot].backend_fd >= 0) {
                            epoll_ctl(epoll_fd, EPOLL_CTL_DEL, sessions[slot].backend_fd, NULL);
                            close(sessions[slot].backend_fd);
                            sessions[slot].backend_fd = -1;
                        }
                        sessions[slot].in_use = 0;
                        continue;
                    }
                    while (1) {
                        ssize_t len = recv(sessions[slot].backend_fd, buffer, sizeof(buffer), MSG_DONTWAIT);
                        if (len <= 0) break;
                        sessions[slot].last_active = now;
                        sendto(listen_fd, buffer, len, MSG_NOSIGNAL, (struct sockaddr *)&sessions[slot].client_addr, sizeof(sessions[slot].client_addr));
                    }
                }
            }
        }
    }

    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (sessions[i].in_use && sessions[i].backend_fd >= 0) {
            close(sessions[i].backend_fd);
        }
    }
    if (epoll_fd >= 0) close(epoll_fd);
    if (listen_fd >= 0) close(listen_fd);
    printf("smite-udp-relay terminated cleanly\n");
    return 0;
}
