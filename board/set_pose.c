#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define CTRL_PHYS 0x40000000u

static uint32_t pack_xy(int x, int y)
{
    if (x < 0) x = 0;
    if (x > 1279) x = 1279;
    if (y < 0) y = 0;
    if (y > 719) y = 719;
    return (((uint32_t)y & 0x3FFu) << 16) | ((uint32_t)x & 0x7FFu);
}

int main(int argc, char** argv)
{
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("open /dev/mem");
        return 1;
    }
    volatile uint32_t* ctrl = (volatile uint32_t*)mmap(
        NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, CTRL_PHYS);
    if (ctrl == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return 1;
    }
    if (ctrl[0] != 0xAC880720u) {
        fprintf(stderr, "Unexpected MAGIC_ID=0x%08x\n", ctrl[0]);
        munmap((void*)ctrl, 4096);
        close(fd);
        return 2;
    }

    if (argc >= 2 && strcmp(argv[1], "clear") == 0) {
        ctrl[6] = 0u;
        ctrl[7] = 0u;
        ctrl[1] = 0x4u;
        printf("Cleared OSD box and skeleton.\n");
    } else {
        // Draw a 17-point sitting pet test skeleton centered on 1280x720 HDMI2
        static const int demo_xy[17][2] = {
            {520, 220}, // 0 left_eye
            {460, 210}, // 1 right_eye
            {470, 250}, // 2 nose
            {530, 320}, // 3 neck
            {760, 480}, // 4 root_of_tail
            {540, 430}, // 5 left_shoulder
            {535, 510}, // 6 left_elbow
            {525, 580}, // 7 left_front_paw
            {505, 430}, // 8 right_shoulder
            {510, 505}, // 9 right_elbow
            {510, 575}, // 10 right_front_paw
            {660, 530}, // 11 left_hip
            {710, 575}, // 12 left_knee
            {640, 600}, // 13 left_back_paw
            {610, 535}, // 14 right_hip
            {650, 570}, // 15 right_knee
            {600, 595}  // 16 right_back_paw
        };
        int label = (argc >= 2 && strcmp(argv[1], "dog") == 0) ? 2 : 1;
        int pose = 2; // default SIT to match sitting demo skeleton
        const char* pose_str = "SIT";
        if (argc >= 3) {
            if (strcmp(argv[2], "unk") == 0)      { pose = 0; pose_str = "UNK"; }
            else if (strcmp(argv[2], "std") == 0) { pose = 1; pose_str = "STD"; }
            else if (strcmp(argv[2], "sit") == 0) { pose = 2; pose_str = "SIT"; }
            else if (strcmp(argv[2], "lie") == 0) { pose = 3; pose_str = "LIE"; }
        }
        ctrl[4] = pack_xy(420, 170);
        ctrl[5] = pack_xy(820, 620);
        ctrl[6] = ((uint32_t)(pose & 0x3) << 3) | ((uint32_t)(label & 0x3) << 1) | 1u;
        for (int i = 0; i < 17; ++i)
            ctrl[8 + i] = pack_xy(demo_xy[i][0], demo_xy[i][1]);
        ctrl[7] = 0x1FFFFu;
        ctrl[1] = 0x4u;
        printf("Committed demo %s-%s box + 17-pt skeleton, BOX_ATTR=0x%02x, KPT_VALID=0x%05x.\n",
               label == 2 ? "DOG" : "CAT", pose_str, ctrl[6], ctrl[7]);
    }

    munmap((void*)ctrl, 4096);
    close(fd);
    return 0;
}
