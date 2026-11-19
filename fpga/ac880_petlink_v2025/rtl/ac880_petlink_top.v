`timescale 1ns/1ps
// AC880PRO Step 2+3+4: PS7 Linux + OV5640-to-HDMI2 + 256x144 BRAM mailbox + PL OSD.
module ac880_petlink_top(
    inout  wire [14:0] DDR_addr,
    inout  wire [2:0]  DDR_ba,
    inout  wire        DDR_cas_n,
    inout  wire        DDR_ck_n,
    inout  wire        DDR_ck_p,
    inout  wire        DDR_cke,
    inout  wire        DDR_cs_n,
    inout  wire [3:0]  DDR_dm,
    inout  wire [31:0] DDR_dq,
    inout  wire [3:0]  DDR_dqs_n,
    inout  wire [3:0]  DDR_dqs_p,
    inout  wire        DDR_odt,
    inout  wire        DDR_ras_n,
    inout  wire        DDR_reset_n,
    inout  wire        DDR_we_n,
    inout  wire        FIXED_IO_ddr_vrn,
    inout  wire        FIXED_IO_ddr_vrp,
    inout  wire [53:0] FIXED_IO_mio,
    inout  wire        FIXED_IO_ps_clk,
    inout  wire        FIXED_IO_ps_porb,
    inout  wire        FIXED_IO_ps_srstb,

    input  wire        sys_clk,
    input  wire        reset_n,
    input  wire        camera_pclk,
    input  wire        camera_vsync,
    input  wire        camera_href,
    input  wire [7:0]  camera_data,
    output wire        camera_xclk,
    output wire        camera_scl,
    inout  wire        camera_sda,
    output wire [3:0]  led,
    output wire [2:0]  tmds_data_p,
    output wire [2:0]  tmds_data_n,
    output wire        tmds_clk_p,
    output wire        tmds_clk_n,
    inout  wire [15:0] ddr3_dq,
    inout  wire [1:0]  ddr3_dqs_p,
    inout  wire [1:0]  ddr3_dqs_n,
    output wire [13:0] ddr3_addr,
    output wire [2:0]  ddr3_ba,
    output wire        ddr3_ras_n,
    output wire        ddr3_cas_n,
    output wire        ddr3_we_n,
    output wire        ddr3_reset_n,
    output wire [0:0]  ddr3_ck_p,
    output wire [0:0]  ddr3_ck_n,
    output wire [0:0]  ddr3_cke,
    output wire [0:0]  ddr3_cs_n,
    output wire [1:0]  ddr3_dm,
    output wire [0:0]  ddr3_odt
);

    wire        axi_clk;
    wire        axi_resetn;
    wire        cmd_req;
    wire        cmd_release;
    wire        status_busy;
    wire        status_ready;
    wire [15:0] frame_seq;
    wire [15:0] last_pix_cnt;
    wire [10:0] sh_x1, sh_x2;
    wire [9:0]  sh_y1, sh_y2;
    wire        sh_valid;
    wire [1:0]  sh_label;
    wire [1:0]  sh_pose;
    wire        sh_commit_toggle;
    wire [17*11-1:0] sh_kpt_x_flat;
    wire [17*10-1:0] sh_kpt_y_flat;
    wire [16:0]      sh_kpt_valid;

    wire        bram_clk;
    wire        bram_rst;
    wire        bram_en;
    wire [3:0]  bram_we;
    wire [31:0] bram_addr;
    wire [31:0] bram_din;
    wire [31:0] bram_dout_unused;

    ps7_sys u_ps7 (
        .DDR_addr          (DDR_addr),
        .DDR_ba            (DDR_ba),
        .DDR_cas_n         (DDR_cas_n),
        .DDR_ck_n          (DDR_ck_n),
        .DDR_ck_p          (DDR_ck_p),
        .DDR_cke           (DDR_cke),
        .DDR_cs_n          (DDR_cs_n),
        .DDR_dm            (DDR_dm),
        .DDR_dq            (DDR_dq),
        .DDR_dqs_n         (DDR_dqs_n),
        .DDR_dqs_p         (DDR_dqs_p),
        .DDR_odt           (DDR_odt),
        .DDR_ras_n         (DDR_ras_n),
        .DDR_reset_n       (DDR_reset_n),
        .DDR_we_n          (DDR_we_n),
        .FIXED_IO_ddr_vrn  (FIXED_IO_ddr_vrn),
        .FIXED_IO_ddr_vrp  (FIXED_IO_ddr_vrp),
        .FIXED_IO_mio      (FIXED_IO_mio),
        .FIXED_IO_ps_clk   (FIXED_IO_ps_clk),
        .FIXED_IO_ps_porb  (FIXED_IO_ps_porb),
        .FIXED_IO_ps_srstb (FIXED_IO_ps_srstb),

        .axi_clk           (axi_clk),
        .axi_resetn        (axi_resetn),
        .cmd_req           (cmd_req),
        .cmd_release       (cmd_release),
        .status_busy       (status_busy),
        .status_ready      (status_ready),
        .frame_seq         (frame_seq),
        .last_pix_cnt      (last_pix_cnt),
        .box_x1            (sh_x1),
        .box_y1            (sh_y1),
        .box_x2            (sh_x2),
        .box_y2            (sh_y2),
        .box_valid         (sh_valid),
        .box_label         (sh_label),
        .box_pose          (sh_pose),
        .box_commit_toggle (sh_commit_toggle),
        .kpt_x_flat        (sh_kpt_x_flat),
        .kpt_y_flat        (sh_kpt_y_flat),
        .kpt_valid         (sh_kpt_valid),

        .BRAM_PORTB_addr   (bram_addr),
        .BRAM_PORTB_clk    (bram_clk),
        .BRAM_PORTB_din    (bram_din),
        .BRAM_PORTB_dout   (bram_dout_unused),
        .BRAM_PORTB_en     (bram_en),
        .BRAM_PORTB_rst    (bram_rst),
        .BRAM_PORTB_we     (bram_we)
    );

    camera_hdmi_petlink_top u_cam (
        .sys_clk           (sys_clk),
        .reset_n           (reset_n),
        .axi_clk           (axi_clk),
        .axi_resetn        (axi_resetn),
        .cmd_req           (cmd_req),
        .cmd_release       (cmd_release),
        .status_busy       (status_busy),
        .status_ready      (status_ready),
        .frame_seq         (frame_seq),
        .last_pix_cnt      (last_pix_cnt),
        .sh_x1             (sh_x1),
        .sh_y1             (sh_y1),
        .sh_x2             (sh_x2),
        .sh_y2             (sh_y2),
        .sh_valid          (sh_valid),
        .sh_label          (sh_label),
        .sh_pose           (sh_pose),
        .sh_commit_toggle  (sh_commit_toggle),
        .sh_kpt_x_flat     (sh_kpt_x_flat),
        .sh_kpt_y_flat     (sh_kpt_y_flat),
        .sh_kpt_valid      (sh_kpt_valid),
        .bram_clk          (bram_clk),
        .bram_rst          (bram_rst),
        .bram_en           (bram_en),
        .bram_we           (bram_we),
        .bram_addr         (bram_addr),
        .bram_din          (bram_din),

        .camera_pclk       (camera_pclk),
        .camera_vsync      (camera_vsync),
        .camera_href       (camera_href),
        .camera_data       (camera_data),
        .camera_xclk       (camera_xclk),
        .camera_scl        (camera_scl),
        .camera_sda        (camera_sda),
        .led               (led),
        .tmds_data_p       (tmds_data_p),
        .tmds_data_n       (tmds_data_n),
        .tmds_clk_p        (tmds_clk_p),
        .tmds_clk_n        (tmds_clk_n),
        .ddr3_dq           (ddr3_dq),
        .ddr3_dqs_p        (ddr3_dqs_p),
        .ddr3_dqs_n        (ddr3_dqs_n),
        .ddr3_addr         (ddr3_addr),
        .ddr3_ba           (ddr3_ba),
        .ddr3_ras_n        (ddr3_ras_n),
        .ddr3_cas_n        (ddr3_cas_n),
        .ddr3_we_n         (ddr3_we_n),
        .ddr3_reset_n      (ddr3_reset_n),
        .ddr3_ck_p         (ddr3_ck_p),
        .ddr3_ck_n         (ddr3_ck_n),
        .ddr3_cke          (ddr3_cke),
        .ddr3_cs_n         (ddr3_cs_n),
        .ddr3_dm           (ddr3_dm),
        .ddr3_odt          (ddr3_odt)
    );

endmodule
