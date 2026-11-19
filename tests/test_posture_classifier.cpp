#include <cassert>
#include <cstdio>
#include "posture_classifier.hpp"

using namespace petlink;

static void make_stand_kpts(int kx[17], int ky[17])
{
    // Box [100, 100] .. [700, 500] (w=600, h=400, aspect=0.67)
    // High horizontal spine: neck_y=0.35, tail_y=0.35, hip_y=0.45, paws_y=0.92
    for (int i = 0; i < 17; ++i) { kx[i] = 400; ky[i] = 300; }
    kx[3]  = 240; ky[3]  = 240; // neck  ny=0.35
    kx[4]  = 580; ky[4]  = 240; // tail  ny=0.35
    kx[5]  = 260; ky[5]  = 280; // l_sh  ny=0.45
    kx[8]  = 275; ky[8]  = 285; // r_sh
    kx[7]  = 250; ky[7]  = 468; // l_fp  ny=0.92
    kx[10] = 285; ky[10] = 468; // r_fp
    kx[11] = 540; ky[11] = 280; // l_hip ny=0.45
    kx[14] = 525; ky[14] = 285; // r_hip
    kx[13] = 550; ky[13] = 468; // l_bp  ny=0.92
    kx[16] = 515; ky[16] = 464; // r_bp  ny=0.91
}

static void make_dog_jpg_sit_kpts(int kx[17], int ky[17])
{
    // Reproduces observed normalized metrics on dog.jpg:
    // box w=400, h=332 (aspect=0.83), neck_y=0.356, tail_y=0.750, hip_y=0.837, paw_y=0.932
    for (int i = 0; i < 17; ++i) { kx[i] = 400; ky[i] = 300; }
    kx[3]  = 260; ky[3]  = 218; // neck (ny ~ 0.355)
    kx[4]  = 452; ky[4]  = 349; // tail (ny ~ 0.750)
    kx[5]  = 280; ky[5]  = 280;
    kx[8]  = 295; ky[8]  = 285;
    kx[7]  = 265; ky[7]  = 410; // front paw
    kx[10] = 290; ky[10] = 410;
    kx[11] = 410; ky[11] = 378; // hip (ny ~ 0.837)
    kx[14] = 395; ky[14] = 378;
    kx[13] = 365; ky[13] = 409; // back paw (ny ~ 0.931)
    kx[16] = 350; ky[16] = 409;
}

static void make_lie_kpts(int kx[17], int ky[17])
{
    // Flat horizontal box [100, 200] .. [700, 520] (w=600, h=320, aspect=0.53)
    for (int i = 0; i < 17; ++i) { kx[i] = 400; ky[i] = 380; }
    kx[3]  = 220; ky[3]  = 330; // neck  ny=0.406
    kx[4]  = 600; ky[4]  = 375; // tail  ny=0.547 -> dy_spine=0.141
    kx[5]  = 250; ky[5]  = 410; // l_sh  ny=0.656
    kx[8]  = 270; ky[8]  = 415;
    kx[7]  = 190; ky[7]  = 468; // fpaws flat near floor (sh_paw_dy=0.18)
    kx[10] = 215; ky[10] = 472;
    kx[11] = 520; ky[11] = 445; // hip   ny=0.766
    kx[14] = 505; ky[14] = 450;
    kx[13] = 460; ky[13] = 475; // bpaws ny=0.859 -> hip_paw_dy=0.07
    kx[16] = 440; ky[16] = 472;
}

int main()
{
    int kx[17], ky[17];

    // 1. STAND vector
    make_stand_kpts(kx, ky);
    PoseId p_std = classify_posture(100, 100, 700, 500, kx, ky, 0x1FFFFu);
    assert(p_std == POSE_STD);

    // 2. SIT vector (dog.jpg geometry)
    make_dog_jpg_sit_kpts(kx, ky);
    PoseId p_sit = classify_posture(100, 100, 500, 432, kx, ky, 0x1FFFFu);
    assert(p_sit == POSE_SIT);

    // 3. LIE vector
    make_lie_kpts(kx, ky);
    PoseId p_lie = classify_posture(100, 200, 700, 520, kx, ky, 0x1FFFFu);
    assert(p_lie == POSE_LIE);

    // 4. Close-up face only (cat.png 3/17 eyes+nose) -> UNK
    PoseId p_unk = classify_posture(100, 100, 500, 392, kx, ky, 0x00007u);
    assert(p_unk == POSE_UNK);

    // 5. 3-frame majority-vote temporal smoother rejects 1-frame jitter
    PoseSmoother sm;
    assert(sm.update(POSE_SIT) == POSE_SIT);
    assert(sm.update(POSE_STD) == POSE_SIT); // 1-1 tie keeps previous stable SIT
    assert(sm.update(POSE_SIT) == POSE_SIT); // 2/3 majority SIT
    assert(sm.update(POSE_LIE) == POSE_SIT); // [STD, SIT, LIE] -> keeps SIT
    assert(sm.update(POSE_LIE) == POSE_LIE); // [SIT, LIE, LIE] -> 2/3 switches to LIE
    sm.on_miss();
    sm.on_miss();                            // 2 misses resets
    assert(sm.update(POSE_STD) == POSE_STD);

    std::printf("ALL_POSTURE_TESTS_PASS\n");
    return 0;
}
