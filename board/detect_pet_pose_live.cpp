#include <algorithm>
#include <arpa/inet.h>
#include <cctype>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>
#include <vector>
#include "net.h"
#include "posture_classifier.hpp"

namespace {
constexpr uint32_t CTRL_PHYS     = 0x40000000u;
constexpr uint32_t BRAM_PHYS     = 0x42000000u;
constexpr size_t   BRAM_MAP_SIZE = 0x20000u;
constexpr int      THUMB_W       = 256;
constexpr int      THUMB_H       = 144;
constexpr int      THUMB_PIXELS  = THUMB_W * THUMB_H;
constexpr int      DISP_W        = 1280;
constexpr int      DISP_H        = 720;
constexpr int      SCALE_STEP    = 5;

volatile sig_atomic_t g_running = 1;
void handle_sig(int) { g_running = 0; }

struct Detection {
    float x1, y1, x2, y2;
    int label;
    float score;
};

uint32_t pack_xy(int x, int y)
{
    x = std::max(0, std::min(x, DISP_W - 1));
    y = std::max(0, std::min(y, DISP_H - 1));
    return (static_cast<uint32_t>(y & 0x3FF) << 16) | static_cast<uint32_t>(x & 0x7FF);
}

void commit_overlay(volatile uint32_t* ctrl, bool valid, int label, int pose,
                    int x1, int y1, int x2, int y2,
                    const int kx[17], const int ky[17], uint32_t kpt_mask)
{
    if (!valid) {
        ctrl[6] = 0u;
        ctrl[7] = 0u;
        ctrl[1] = 0x4u;
        return;
    }
    ctrl[4] = pack_xy(x1, y1);
    ctrl[5] = pack_xy(x2, y2);
    ctrl[6] = (static_cast<uint32_t>(pose & 0x3) << 3) |
              (static_cast<uint32_t>(label & 0x3) << 1) | 1u;
    for (int k = 0; k < 17; ++k) {
        if (kpt_mask & (1u << k))
            ctrl[8 + k] = pack_xy(kx[k], ky[k]);
        else
            ctrl[8 + k] = 0u;
    }
    ctrl[7] = kpt_mask & 0x1FFFFu;
    ctrl[1] = 0x4u;
}

// Bilinear RGB crop from 256x144 thumbnail into 256x256 buffer (RGB or BGR order)
void crop_square_bilinear(const uint8_t* rgb, int w, int h,
                          float sx0, float sy0, float side,
                          bool swap_rb, uint8_t* dst, int dst_size)
{
    const float ratio = side / static_cast<float>(dst_size);
    for (int dy = 0; dy < dst_size; ++dy) {
        const float fy = sy0 + (dy + 0.5f) * ratio - 0.5f;
        const int iy0 = static_cast<int>(std::floor(fy));
        const int iy1 = iy0 + 1;
        const float wy = fy - iy0;
        for (int dx = 0; dx < dst_size; ++dx) {
            const float fx = sx0 + (dx + 0.5f) * ratio - 0.5f;
            const int ix0 = static_cast<int>(std::floor(fx));
            const int ix1 = ix0 + 1;
            const float wx = fx - ix0;

            float acc[3] = {0.f, 0.f, 0.f};
            const int xs[2] = {ix0, ix1};
            const int ys[2] = {iy0, iy1};
            const float wxs[2] = {1.f - wx, wx};
            const float wys[2] = {1.f - wy, wy};
            for (int ry = 0; ry < 2; ++ry) {
                if (ys[ry] < 0 || ys[ry] >= h) continue;
                for (int rx = 0; rx < 2; ++rx) {
                    if (xs[rx] < 0 || xs[rx] >= w) continue;
                    const float wt = wys[ry] * wxs[rx];
                    const size_t sp = (static_cast<size_t>(ys[ry]) * w + xs[rx]) * 3;
                    acc[0] += wt * rgb[sp + 0];
                    acc[1] += wt * rgb[sp + 1];
                    acc[2] += wt * rgb[sp + 2];
                }
            }
            const size_t dp = (static_cast<size_t>(dy) * dst_size + dx) * 3;
            uint8_t r = static_cast<uint8_t>(std::max(0.f, std::min(255.f, acc[0] + 0.5f)));
            uint8_t g = static_cast<uint8_t>(std::max(0.f, std::min(255.f, acc[1] + 0.5f)));
            uint8_t b = static_cast<uint8_t>(std::max(0.f, std::min(255.f, acc[2] + 0.5f)));
            if (swap_rb) {
                dst[dp + 0] = b; dst[dp + 1] = g; dst[dp + 2] = r;
            } else {
                dst[dp + 0] = r; dst[dp + 1] = g; dst[dp + 2] = b;
            }
        }
    }
}
struct UdpSender {
    int fd = -1;
    sockaddr_in dst{};

    bool open_target(const char* ip_port)
    {
        if (!ip_port || !*ip_port) return false;
        const char* colon = std::strrchr(ip_port, ':');
        if (!colon || colon == ip_port || !*(colon + 1)) {
            std::fprintf(stderr, "Invalid --udp format '%s' (expected ip:port)\n", ip_port);
            return false;
        }
        char ip_buf[64] = {0};
        size_t ip_len = static_cast<size_t>(colon - ip_port);
        if (ip_len >= sizeof(ip_buf)) return false;
        std::memcpy(ip_buf, ip_port, ip_len);
        int port = std::atoi(colon + 1);
        if (port <= 0 || port > 65535) return false;

        fd = socket(AF_INET, SOCK_DGRAM, 0);
        if (fd < 0) {
            std::perror("socket UDP");
            return false;
        }
        int bcast = 1;
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &bcast, sizeof(bcast));
        std::memset(&dst, 0, sizeof(dst));
        dst.sin_family = AF_INET;
        dst.sin_port = htons(static_cast<uint16_t>(port));
        if (inet_pton(AF_INET, ip_buf, &dst.sin_addr) != 1) {
            std::fprintf(stderr, "Invalid UDP IPv4 address '%s'\n", ip_buf);
            close(fd);
            fd = -1;
            return false;
        }
        std::printf("UDP output enabled -> %s:%d\n", ip_buf, port);
        return true;
    }

    void send_json(const char* payload, size_t len) const
    {
        if (fd < 0) return;
        sendto(fd, payload, len, 0, reinterpret_cast<const sockaddr*>(&dst), sizeof(dst));
    }

    ~UdpSender()
    {
        if (fd >= 0) close(fd);
    }
};
} // namespace

int main(int argc, char** argv)
{
    std::vector<const char*> pos;
    const char* udp_target = nullptr;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--udp") == 0 && i + 1 < argc) {
            udp_target = argv[++i];
        } else {
            pos.push_back(argv[i]);
        }
    }
    if (!pos.empty() && pos.size() < 4 && !std::isdigit(static_cast<unsigned char>(pos[0][0]))) {
        std::fprintf(stderr,
            "usage: %s [det.param det.bin pose.param pose.bin [max_iters=0] [det_size=320] [kpt_thr=0.72]] [--udp ip:port]\n"
            "   or: %s [max_iters=0] [kpt_thr=0.72] [--udp ip:port]  (uses default Option B models)\n",
            argv[0], argv[0]);
        return 1;
    }
    const bool  explicit_models = (pos.size() >= 4);
    const char* det_param  = explicit_models ? pos[0] : "yolov5n_v7.0_320.ncnn.param";
    const char* det_bin    = explicit_models ? pos[1] : "yolov5n_v7.0_320.ncnn.bin";
    const char* pose_param = explicit_models ? pos[2] : "rtmpose_m_ap10k_256_int8.ncnn.param";
    const char* pose_bin   = explicit_models ? pos[3] : "rtmpose_m_ap10k_256_int8.ncnn.bin";
    const int   max_iters  = explicit_models ? ((pos.size() >= 5) ? std::atoi(pos[4]) : 0)
                                             : ((pos.size() >= 1) ? std::atoi(pos[0]) : 0);
    const int   det_size   = (explicit_models && pos.size() >= 6) ? std::atoi(pos[5]) : 320;
    const float kpt_thr    = explicit_models ? ((pos.size() >= 7) ? static_cast<float>(std::atof(pos[6])) : 0.72f)
                                             : ((pos.size() >= 2) ? static_cast<float>(std::atof(pos[1])) : 0.72f);

    UdpSender udp;
    if (udp_target && !udp.open_target(udp_target)) return 1;

    std::signal(SIGINT, handle_sig);
    std::signal(SIGTERM, handle_sig);

    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        std::perror("open /dev/mem");
        return 1;
    }
    auto* ctrl = static_cast<volatile uint32_t*>(
        mmap(nullptr, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, CTRL_PHYS));
    auto* bram = static_cast<volatile uint32_t*>(
        mmap(nullptr, BRAM_MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BRAM_PHYS));
    if (ctrl == MAP_FAILED || bram == MAP_FAILED) {
        std::perror("mmap");
        if (ctrl != MAP_FAILED) munmap((void*)ctrl, 4096);
        if (bram != MAP_FAILED) munmap((void*)bram, BRAM_MAP_SIZE);
        close(fd);
        return 1;
    }
    if (ctrl[0] != 0xAC880720u) {
        std::fprintf(stderr, "Unexpected PL_ID=0x%08x\n", ctrl[0]);
        munmap((void*)ctrl, 4096);
        munmap((void*)bram, BRAM_MAP_SIZE);
        close(fd);
        return 2;
    }

    ncnn::Net det_net, pose_net;
    det_net.opt.num_threads = 2;
    det_net.opt.use_vulkan_compute = false;
    pose_net.opt.num_threads = 2;
    pose_net.opt.use_vulkan_compute = false;

    if (det_net.load_param(det_param) != 0 || det_net.load_model(det_bin) != 0 ||
        pose_net.load_param(pose_param) != 0 || pose_net.load_model(pose_bin) != 0) {
        std::fprintf(stderr, "Model load failed\n");
        munmap((void*)ctrl, 4096);
        munmap((void*)bram, BRAM_MAP_SIZE);
        close(fd);
        return 3;
    }

    const float det_scale = std::min(static_cast<float>(det_size) / THUMB_W,
                                     static_cast<float>(det_size) / THUMB_H);
    const int dw = static_cast<int>(std::round(THUMB_W * det_scale));
    const int dh = static_cast<int>(std::round(THUMB_H * det_scale));
    const int dleft = (det_size - dw) / 2;
    const int dtop  = (det_size - dh) / 2;
    const float dnorm[3] = {1.f / 255.f, 1.f / 255.f, 1.f / 255.f};
    const float pmean[3] = {123.675f, 116.28f, 103.53f};
    const float pnorm[3] = {1.f / 58.395f, 1.f / 57.12f, 1.f / 57.375f};
    const int psize = 256;

    std::vector<uint32_t> raw_words(THUMB_PIXELS / 2);
    std::vector<uint8_t>  rgb(THUMB_PIXELS * 3);
    std::vector<uint8_t>  crop(psize * psize * 3);

    int iter = 0;
    int zero_kx[17] = {0}, zero_ky[17] = {0};
    petlink::PoseSmoother pose_smoother;
    char json_buf[256];

    while (g_running && (max_iters <= 0 || iter < max_iters)) {
        const auto loop_t0 = std::chrono::steady_clock::now();

        if (ctrl[2] & 0x2u) {
            ctrl[1] = 0x2u;
            usleep(200);
        }
        ctrl[1] = 0x1u;
        int wait_us = 1000000;
        while (!(ctrl[2] & 0x2u)) {
            if (!g_running || wait_us <= 0) break;
            usleep(500);
            wait_us -= 500;
        }
        if (!g_running) break;
        if (!(ctrl[2] & 0x2u)) {
            std::fprintf(stderr, "Timeout waiting frame\n");
            commit_overlay(ctrl, false, 0, 0, 0, 0, 0, 0, zero_kx, zero_ky, 0u);
            continue;
        }

        for (size_t i = 0; i < raw_words.size(); ++i)
            raw_words[i] = bram[i];
        ctrl[1] = 0x2u; // release BRAM lock immediately before inference
        const auto grab_t1 = std::chrono::steady_clock::now();

        const uint16_t* pix16 = reinterpret_cast<const uint16_t*>(raw_words.data());
        for (int i = 0; i < THUMB_PIXELS; ++i) {
            uint16_t c = pix16[i];
            uint8_t r5 = (c >> 11) & 0x1F;
            uint8_t g6 = (c >> 5) & 0x3F;
            uint8_t b5 = c & 0x1F;
            rgb[i * 3 + 0] = (r5 << 3) | (r5 >> 2);
            rgb[i * 3 + 1] = (g6 << 2) | (g6 >> 4);
            rgb[i * 3 + 2] = (b5 << 3) | (b5 >> 2);
        }

        // 1. Detection
        ncnn::Mat resized = ncnn::Mat::from_pixels_resize(
            rgb.data(), ncnn::Mat::PIXEL_RGB, THUMB_W, THUMB_H, dw, dh);
        ncnn::Mat det_in;
        ncnn::copy_make_border(resized, det_in, dtop, det_size - dh - dtop, dleft, det_size - dw - dleft,
                               ncnn::BORDER_CONSTANT, 114.f);
        det_in.substract_mean_normalize(0, dnorm);

        ncnn::Extractor dex = det_net.create_extractor();
        dex.input("in0", det_in);
        ncnn::Mat det_out;
        const auto det_t0 = std::chrono::steady_clock::now();
        int status = dex.extract("out0", det_out);
        const auto det_t1 = std::chrono::steady_clock::now();
        const double det_ms = std::chrono::duration<double, std::milli>(det_t1 - det_t0).count();

        Detection best{};
        bool has_best = false;
        if (status == 0 && det_out.dims == 2 && det_out.w == 85) {
            for (int i = 0; i < det_out.h; ++i) {
                const float* p = det_out.row(i);
                int label = 0;
                for (int c = 1; c < 80; ++c) if (p[5 + c] > p[5 + label]) label = c;
                float score = p[4] * p[5 + label];
                if ((label != 15 && label != 16) || score < 0.25f) continue;
                float x1 = std::max(0.f, std::min((p[0] - p[2] * 0.5f - dleft) / det_scale, (float)(THUMB_W - 1)));
                float y1 = std::max(0.f, std::min((p[1] - p[3] * 0.5f - dtop)  / det_scale, (float)(THUMB_H - 1)));
                float x2 = std::max(0.f, std::min((p[0] + p[2] * 0.5f - dleft) / det_scale, (float)(THUMB_W - 1)));
                float y2 = std::max(0.f, std::min((p[1] + p[3] * 0.5f - dtop)  / det_scale, (float)(THUMB_H - 1)));
                if (x2 > x1 && y2 > y1 && (!has_best || score > best.score)) {
                    best = {x1, y1, x2, y2, label, score};
                    has_best = true;
                }
            }
        }

        const double grab_ms = std::chrono::duration<double, std::milli>(grab_t1 - loop_t0).count();

        if (!has_best) {
            pose_smoother.on_miss();
            commit_overlay(ctrl, false, 0, 0, 0, 0, 0, 0, zero_kx, zero_ky, 0u);
            const double total_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - loop_t0).count();
            int n = std::snprintf(
                json_buf, sizeof(json_buf),
                "{\"seq\":%d,\"valid\":0,\"cls\":\"NONE\",\"score\":0.00,\"pose\":\"UNK\",\"raw\":\"UNK\",\"kpt_cnt\":0,\"box\":[0,0,0,0],\"ms\":%.1f}",
                iter, total_ms);
            if (n > 0) udp.send_json(json_buf, static_cast<size_t>(n));
            std::printf("[%d] NONE grab=%.1fms det=%.1fms\n", iter, grab_ms, det_ms);
            std::fflush(stdout);
            ++iter;
            continue;
        }

        // 2. Top-down 1.25x padded square crop -> 256x256
        const float cx = 0.5f * (best.x1 + best.x2);
        const float cy = 0.5f * (best.y1 + best.y2);
        const float side = std::max(best.x2 - best.x1, best.y2 - best.y1) * 1.25f;
        const float sx0 = cx - 0.5f * side;
        const float sy0 = cy - 0.5f * side;

        crop_square_bilinear(rgb.data(), THUMB_W, THUMB_H, sx0, sy0, side, true, crop.data(), psize);
        ncnn::Mat pose_in = ncnn::Mat::from_pixels(crop.data(), ncnn::Mat::PIXEL_RGB, psize, psize);
        pose_in.substract_mean_normalize(pmean, pnorm);

        ncnn::Extractor pex = pose_net.create_extractor();
        pex.input("in0", pose_in);
        ncnn::Mat out_x, out_y;
        const auto pose_t0 = std::chrono::steady_clock::now();
        pex.extract("out0", out_x);
        pex.extract("out1", out_y);
        const auto pose_t1 = std::chrono::steady_clock::now();
        const double pose_ms = std::chrono::duration<double, std::milli>(pose_t1 - pose_t0).count();

        int disp_kx[17] = {0}, disp_ky[17] = {0};
        uint32_t kpt_mask = 0u;
        int kpt_cnt = 0;

        for (int k = 0; k < 17; ++k) {
            const float* rx = out_x.row(k);
            const float* ry = out_y.row(k);
            int bx = 0, by = 0;
            for (int j = 1; j < out_x.w; ++j) if (rx[j] > rx[bx]) bx = j;
            for (int j = 1; j < out_y.w; ++j) if (ry[j] > ry[by]) by = j;

            float ks = std::min(rx[bx], ry[by]);
            float tx = sx0 + (bx * 0.5f / psize) * side;
            float ty = sy0 + (by * 0.5f / psize) * side;
            bool in_box = (tx >= best.x1 - 4.f && tx <= best.x2 + 4.f &&
                           ty >= best.y1 - 4.f && ty <= best.y2 + 4.f);
            if (ks >= kpt_thr && in_box) {
                disp_kx[k] = static_cast<int>(std::round(tx * SCALE_STEP));
                disp_ky[k] = static_cast<int>(std::round(ty * SCALE_STEP));
                kpt_mask |= (1u << k);
                ++kpt_cnt;
            }
        }

        const int dx1 = static_cast<int>(std::round(best.x1 * SCALE_STEP));
        const int dy1 = static_cast<int>(std::round(best.y1 * SCALE_STEP));
        const int dx2 = static_cast<int>(std::round(best.x2 * SCALE_STEP));
        const int dy2 = static_cast<int>(std::round(best.y2 * SCALE_STEP));
        const int osd_lbl = (best.label == 15) ? 1 : 2;
        const int raw_pose = petlink::classify_posture(dx1, dy1, dx2, dy2, disp_kx, disp_ky, kpt_mask);
        const int smooth_pose = pose_smoother.update(raw_pose);
        commit_overlay(ctrl, true, osd_lbl, smooth_pose, dx1, dy1, dx2, dy2, disp_kx, disp_ky, kpt_mask);

        const double total_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - loop_t0).count();
        const char* cls_str = (best.label == 15) ? "CAT" : "DOG";
        const char* pose_str = petlink::pose_name(smooth_pose);
        const char* raw_str  = petlink::pose_name(raw_pose);
        int n = std::snprintf(
            json_buf, sizeof(json_buf),
            "{\"seq\":%d,\"valid\":1,\"cls\":\"%s\",\"score\":%.2f,\"pose\":\"%s\",\"raw\":\"%s\",\"kpt_cnt\":%d,\"box\":[%d,%d,%d,%d],\"ms\":%.1f}",
            iter, cls_str, best.score, pose_str, raw_str, kpt_cnt, dx1, dy1, dx2, dy2, total_ms);
        if (n > 0) udp.send_json(json_buf, static_cast<size_t>(n));
        std::printf("[%d] %s-%s (raw=%s) %.3f box=(%d,%d,%d,%d) kpts=%d/17 grab=%.1fms det=%.1fms pose=%.1fms total=%.1fms (%.2f Hz)\n",
                    iter, cls_str, pose_str, raw_str, best.score,
                    dx1, dy1, dx2, dy2, kpt_cnt,
                    grab_ms, det_ms, pose_ms, total_ms, 1000.0 / total_ms);
        std::fflush(stdout);
        ++iter;
    }

    commit_overlay(ctrl, false, 0, 0, 0, 0, 0, 0, zero_kx, zero_ky, 0u);
    munmap((void*)ctrl, 4096);
    munmap((void*)bram, BRAM_MAP_SIZE);
    close(fd);
    return 0;
}
