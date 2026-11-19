`timescale 1ns/1ps
// AXI4-Lite slave register block for PS-PL Petlink control, status, OSD box, and 17-joint skeleton.
// Register map (byte offset, 4KB window mapped at 0x40000000):
//   0x00 : MAGIC_ID (0xAC88_0720, RO)
//   0x04 : CTRL (WO: bit0=CAPTURE_REQ, bit1=CAPTURE_RELEASE, bit2=OSD_COMMIT)
//   0x08 : STATUS (RO: bit0=BUSY, bit1=READY, [31:16]=FRAME_SEQ)
//   0x0C : PIX_CNT (RO: [15:0]=LAST_PIX_CNT)
//   0x10 : BOX_XY1 (RW: [10:0]=x1, [25:16]=y1)
//   0x14 : BOX_XY2 (RW: [10:0]=x2, [25:16]=y2)
//   0x18 : BOX_ATTR (RW: bit0=valid, [2:1]=label 1:CAT 2:DOG, [4:3]=pose 0:UNK 1:STD 2:SIT 3:LIE)
//   0x1C : KPT_VALID (RW: [16:0]=17-keypoint valid mask)
//   0x20 + 4*i (i=0..16 -> 0x20..0x60) : KPT_XY[i] (RW: [10:0]=x, [25:16]=y)
module petlink_ctrl_regs #(
    parameter integer C_S_AXI_ADDR_WIDTH = 8
)(
    input  wire                          s_axi_aclk,
    input  wire                          s_axi_aresetn,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_awaddr,
    input  wire [2:0]                    s_axi_awprot,
    input  wire                          s_axi_awvalid,
    output reg                           s_axi_awready,

    input  wire [31:0]                   s_axi_wdata,
    input  wire [3:0]                    s_axi_wstrb,
    input  wire                          s_axi_wvalid,
    output reg                           s_axi_wready,

    output reg  [1:0]                    s_axi_bresp,
    output reg                           s_axi_bvalid,
    input  wire                          s_axi_bready,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_araddr,
    input  wire [2:0]                    s_axi_arprot,
    input  wire                          s_axi_arvalid,
    output reg                           s_axi_arready,

    output reg  [31:0]                   s_axi_rdata,
    output reg  [1:0]                    s_axi_rresp,
    output reg                           s_axi_rvalid,
    input  wire                          s_axi_rready,

    // Mailbox interface (axi_clk domain)
    output reg                           cmd_req,
    output reg                           cmd_release,
    input  wire                          status_busy,
    input  wire                          status_ready,
    input  wire [15:0]                   frame_seq,
    input  wire [15:0]                   last_pix_cnt,

    // OSD shadow outputs (axi_clk domain)
    output reg  [10:0]                   box_x1,
    output reg  [9:0]                    box_y1,
    output reg  [10:0]                   box_x2,
    output reg  [9:0]                    box_y2,
    output reg                           box_valid,
    output reg  [1:0]                    box_label,
    output reg  [1:0]                    box_pose,
    output reg                           box_commit_toggle,

    // 17-keypoint skeleton shadow outputs (axi_clk domain, flattened for BD export)
    output wire [17*11-1:0]              kpt_x_flat,
    output wire [17*10-1:0]              kpt_y_flat,
    output reg  [16:0]                   kpt_valid
);

    localparam [31:0] MAGIC_ID = 32'hAC88_0720;

    reg [10:0] kpt_x_mem [0:16];
    reg [9:0]  kpt_y_mem [0:16];

    genvar gi;
    generate
        for (gi = 0; gi < 17; gi = gi + 1) begin : g_kpt_pack
            assign kpt_x_flat[gi*11 +: 11] = kpt_x_mem[gi];
            assign kpt_y_flat[gi*10 +: 10] = kpt_y_mem[gi];
        end
    endgenerate

    reg [C_S_AXI_ADDR_WIDTH-1:0] awaddr_latched;
    reg aw_seen, w_seen;
    wire [5:0] wr_word_idx = aw_seen ? awaddr_latched[7:2] : s_axi_awaddr[7:2];
    wire [5:0] rd_word_idx = s_axi_araddr[7:2];

    integer idx;

    always @(posedge s_axi_aclk or negedge s_axi_aresetn) begin
        if (!s_axi_aresetn) begin
            s_axi_awready     <= 1'b0;
            s_axi_wready      <= 1'b0;
            s_axi_bvalid      <= 1'b0;
            s_axi_bresp       <= 2'b00;
            awaddr_latched    <= {C_S_AXI_ADDR_WIDTH{1'b0}};
            aw_seen           <= 1'b0;
            w_seen            <= 1'b0;
            cmd_req           <= 1'b0;
            cmd_release       <= 1'b0;
            box_x1            <= 11'd0;
            box_y1            <= 10'd0;
            box_x2            <= 11'd0;
            box_y2            <= 10'd0;
            box_valid         <= 1'b0;
            box_label         <= 2'd0;
            box_pose          <= 2'd0;
            box_commit_toggle <= 1'b0;
            kpt_valid         <= 17'd0;
            for (idx = 0; idx < 17; idx = idx + 1) begin
                kpt_x_mem[idx] <= 11'd0;
                kpt_y_mem[idx] <= 10'd0;
            end
        end else begin
            cmd_req     <= 1'b0;
            cmd_release <= 1'b0;

            if (s_axi_bvalid && s_axi_bready)
                s_axi_bvalid <= 1'b0;

            s_axi_awready <= !aw_seen && !s_axi_bvalid && s_axi_awvalid;
            s_axi_wready  <= !w_seen  && !s_axi_bvalid && s_axi_wvalid;

            if (s_axi_awvalid && s_axi_awready) begin
                aw_seen        <= 1'b1;
                awaddr_latched <= s_axi_awaddr;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                w_seen <= 1'b1;
            end

            if ((aw_seen || (s_axi_awvalid && s_axi_awready)) &&
                (w_seen  || (s_axi_wvalid  && s_axi_wready))  && !s_axi_bvalid) begin
                aw_seen      <= 1'b0;
                w_seen       <= 1'b0;
                s_axi_bvalid <= 1'b1;
                s_axi_bresp  <= 2'b00;

                if (wr_word_idx == 6'h01) begin // 0x04 CTRL
                    if (s_axi_wstrb[0]) begin
                        cmd_req     <= s_axi_wdata[0];
                        cmd_release <= s_axi_wdata[1];
                        if (s_axi_wdata[2])
                            box_commit_toggle <= ~box_commit_toggle;
                    end
                end else if (wr_word_idx == 6'h04) begin // 0x10 BOX_XY1
                    if (s_axi_wstrb[0] && s_axi_wstrb[1]) box_x1 <= s_axi_wdata[10:0];
                    if (s_axi_wstrb[2] && s_axi_wstrb[3]) box_y1 <= s_axi_wdata[25:16];
                end else if (wr_word_idx == 6'h05) begin // 0x14 BOX_XY2
                    if (s_axi_wstrb[0] && s_axi_wstrb[1]) box_x2 <= s_axi_wdata[10:0];
                    if (s_axi_wstrb[2] && s_axi_wstrb[3]) box_y2 <= s_axi_wdata[25:16];
                end else if (wr_word_idx == 6'h06) begin // 0x18 BOX_ATTR
                    if (s_axi_wstrb[0]) begin
                        box_valid <= s_axi_wdata[0];
                        box_label <= s_axi_wdata[2:1];
                        box_pose  <= s_axi_wdata[4:3];
                    end
                end else if (wr_word_idx == 6'h07) begin // 0x1C KPT_VALID
                    if (s_axi_wstrb[0]) kpt_valid[7:0]   <= s_axi_wdata[7:0];
                    if (s_axi_wstrb[1]) kpt_valid[15:8]  <= s_axi_wdata[15:8];
                    if (s_axi_wstrb[2]) kpt_valid[16]    <= s_axi_wdata[16];
                end else if (wr_word_idx >= 6'h08 && wr_word_idx <= 6'h18) begin // 0x20..0x60 KPT_XY[0..16]
                    if (s_axi_wstrb[0] && s_axi_wstrb[1])
                        kpt_x_mem[wr_word_idx - 6'h08] <= s_axi_wdata[10:0];
                    if (s_axi_wstrb[2] && s_axi_wstrb[3])
                        kpt_y_mem[wr_word_idx - 6'h08] <= s_axi_wdata[25:16];
                end
            end
        end
    end

    always @(posedge s_axi_aclk or negedge s_axi_aresetn) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 1'b0;
            s_axi_rvalid  <= 1'b0;
            s_axi_rresp   <= 2'b00;
            s_axi_rdata   <= 32'd0;
        end else begin
            if (s_axi_rvalid && s_axi_rready)
                s_axi_rvalid <= 1'b0;

            s_axi_arready <= !s_axi_rvalid && s_axi_arvalid;

            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                s_axi_rresp  <= 2'b00;
                if (rd_word_idx == 6'h00)
                    s_axi_rdata <= MAGIC_ID;
                else if (rd_word_idx == 6'h02)
                    s_axi_rdata <= {frame_seq, 14'd0, status_ready, status_busy};
                else if (rd_word_idx == 6'h03)
                    s_axi_rdata <= {16'd0, last_pix_cnt};
                else if (rd_word_idx == 6'h04)
                    s_axi_rdata <= {6'd0, box_y1, 5'd0, box_x1};
                else if (rd_word_idx == 6'h05)
                    s_axi_rdata <= {6'd0, box_y2, 5'd0, box_x2};
                else if (rd_word_idx == 6'h06)
                    s_axi_rdata <= {27'd0, box_pose, box_label, box_valid};
                else if (rd_word_idx == 6'h07)
                    s_axi_rdata <= {15'd0, kpt_valid};
                else if (rd_word_idx >= 6'h08 && rd_word_idx <= 6'h18)
                    s_axi_rdata <= {6'd0, kpt_y_mem[rd_word_idx - 6'h08], 5'd0, kpt_x_mem[rd_word_idx - 6'h08]};
                else
                    s_axi_rdata <= 32'd0;
            end
        end
    end

endmodule
