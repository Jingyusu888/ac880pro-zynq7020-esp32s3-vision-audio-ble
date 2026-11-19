#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace petlink {

enum PoseId : int {
    POSE_UNK = 0,
    POSE_STD = 1,
    POSE_SIT = 2,
    POSE_LIE = 3
};

inline const char* pose_name(int pose)
{
    switch (pose) {
    case POSE_STD: return "STD";
    case POSE_SIT: return "SIT";
    case POSE_LIE: return "LIE";
    default:       return "UNK";
    }
}

struct PoseFeatures {
    float box_aspect;
    float dy_spine;
    float dx_spine;
    float rear_y;
    float mean_hip_y;
    float mean_paw_y;
    float hip_paw_dy;
    int   kpt_cnt;
    bool  anchored;
};

// Classify quadruped posture from 17 AP-10K keypoints inside display box [x1,y1,x2,y2].
// Indices: 3=neck, 4=tail_root, 5/8=l/r_shoulder, 7/10=l/r_fpaw, 11/14=l/r_hip, 13/16=l/r_bpaw.
inline PoseId classify_posture(int x1, int y1, int x2, int y2,
                               const int kx[17], const int ky[17],
                               uint32_t kpt_mask, PoseFeatures* out_feat = nullptr)
{
    const float w = std::max(1.0f, static_cast<float>(x2 - x1));
    const float h = std::max(1.0f, static_cast<float>(y2 - y1));

    float nx[17], ny[17];
    int kpt_cnt = 0;
    for (int k = 0; k < 17; ++k) {
        if (kpt_mask & (1u << k)) {
            nx[k] = (static_cast<float>(kx[k]) - x1) / w;
            ny[k] = (static_cast<float>(ky[k]) - y1) / h;
            ++kpt_cnt;
        } else {
            nx[k] = 0.0f;
            ny[k] = 0.0f;
        }
    }

    auto has = [&](int idx) -> bool { return (kpt_mask & (1u << idx)) != 0; };
    auto mean2_y = [&](int a, int b, float& dst) -> bool {
        if (has(a) && has(b)) { dst = 0.5f * (ny[a] + ny[b]); return true; }
        if (has(a)) { dst = ny[a]; return true; }
        if (has(b)) { dst = ny[b]; return true; }
        return false;
    };
    auto mean2_x = [&](int a, int b, float& dst) -> bool {
        if (has(a) && has(b)) { dst = 0.5f * (nx[a] + nx[b]); return true; }
        if (has(a)) { dst = nx[a]; return true; }
        if (has(b)) { dst = nx[b]; return true; }
        return false;
    };

    float hip_x = 0.0f, hip_y = 0.0f;
    const bool has_hip = mean2_x(11, 14, hip_x) && mean2_y(11, 14, hip_y);
    const bool has_neck = has(3);
    const bool has_tail = has(4);

    float rear_x = has_tail ? nx[4] : hip_x;
    float rear_y = has_tail ? ny[4] : hip_y;
    if (!has_hip) hip_y = rear_y;

    float sh_y = 0.0f;
    const bool has_sh = mean2_y(5, 8, sh_y);

    float paw_sum = 0.0f;
    int paw_cnt = 0;
    const int paw_ids[4] = {7, 10, 13, 16};
    for (int id : paw_ids) {
        if (has(id)) {
            paw_sum += ny[id];
            ++paw_cnt;
        }
    }
    const float mean_paw_y = (paw_cnt > 0) ? (paw_sum / paw_cnt) : rear_y;

    const bool anchored = has_neck && (has_tail || has_hip) &&
                          (kpt_cnt >= 6) && (paw_cnt >= 1 || has_hip);

    const float box_aspect = h / w;
    const float dy_spine   = anchored ? (rear_y - ny[3]) : 0.0f;
    const float dx_spine   = anchored ? std::fabs(nx[3] - rear_x) : 0.0f;
    const float hip_paw_dy = (paw_cnt > 0) ? (mean_paw_y - hip_y) : 0.0f;

    if (out_feat) {
        *out_feat = {box_aspect, dy_spine, dx_spine, rear_y,
                     hip_y, mean_paw_y, hip_paw_dy, kpt_cnt, anchored};
    }

    if (!anchored) return POSE_UNK;

    // 1. Standing: clear vertical leg drop below hips/shoulders and rump not sitting low
    const float sh_paw_dy = has_sh ? (mean_paw_y - sh_y) : hip_paw_dy;
    if ((paw_cnt >= 2 && hip_paw_dy >= 0.20f && rear_y < 0.72f) ||
        (paw_cnt >= 2 && sh_paw_dy >= 0.30f && dy_spine < 0.25f && rear_y < 0.65f)) {
        return POSE_STD;
    }

    // 2. Sitting: steeply pitched spine (neck high, rump/tail low near ground)
    if ((dy_spine >= 0.28f && rear_y >= 0.60f) ||
        (dy_spine >= 0.24f && box_aspect >= 0.80f && rear_y >= 0.58f)) {
        return POSE_SIT;
    }

    // 3. Lying: low vertical leg drop with torso flat/low
    if ((paw_cnt >= 1 && hip_paw_dy < 0.20f && dy_spine < 0.28f) ||
        (dy_spine < 0.24f && box_aspect < 0.90f)) {
        return POSE_LIE;
    }

    return POSE_UNK;
}

class PoseSmoother {
public:
    void reset()
    {
        hist_[0] = hist_[1] = hist_[2] = POSE_UNK;
        len_ = 0;
        miss_streak_ = 0;
        stable_ = POSE_UNK;
    }

    void on_miss()
    {
        if (++miss_streak_ >= 2) reset();
    }

    int update(int raw_pose)
    {
        miss_streak_ = 0;
        if (len_ < 3) {
            hist_[len_++] = raw_pose;
        } else {
            hist_[0] = hist_[1];
            hist_[1] = hist_[2];
            hist_[2] = raw_pose;
        }
        int counts[4] = {0, 0, 0, 0};
        for (int i = 0; i < len_; ++i) {
            int p = hist_[i];
            if (p >= 0 && p < 4) ++counts[p];
        }
        for (int p = 0; p < 4; ++p) {
            if (counts[p] >= 2) {
                stable_ = p;
                return stable_;
            }
        }
        if (stable_ == POSE_UNK || len_ == 1) stable_ = raw_pose;
        return stable_;
    }

private:
    int hist_[3] = {POSE_UNK, POSE_UNK, POSE_UNK};
    int len_ = 0;
    int miss_streak_ = 0;
    int stable_ = POSE_UNK;
};

} // namespace petlink
