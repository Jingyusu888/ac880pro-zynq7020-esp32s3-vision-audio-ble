`timescale 1ns/1ps
// Pixel-stream OSD overlay (720p, 1-cycle pipelined with matched hs/vs/de outputs):
//   - 1 bounding box + CAT/DOG 8x8 2x scaled bitmap label
//   - 17 animal keypoints (green dots) + 17 skeleton segments (streaming integer distance check)
// Latches committed shadow parameters cleanly on vs_frame_start.
module petlink_osd(
    input  wire             pixel_clk,
    input  wire             pixel_reset,
    input  wire             vs_frame_start,
    input  wire             in_hs,
    input  wire             in_vs,
    input  wire             de,
    input  wire [10:0]      pixel_x,
    input  wire [9:0]       pixel_y,
    input  wire [7:0]       in_r,
    input  wire [7:0]       in_g,
    input  wire [7:0]       in_b,

    // Committed shadow inputs from axi_clk domain
    input  wire [10:0]      sh_x1,
    input  wire [9:0]       sh_y1,
    input  wire [10:0]      sh_x2,
    input  wire [9:0]       sh_y2,
    input  wire             sh_valid,
    input  wire [1:0]       sh_label,
    input  wire [1:0]       sh_pose,
    input  wire             sh_commit_toggle,
    input  wire [17*11-1:0] sh_kpt_x_flat,
    input  wire [17*10-1:0] sh_kpt_y_flat,
    input  wire [16:0]      sh_kpt_valid,

    output wire             out_hs,
    output wire             out_vs,
    output wire             out_de,
    output wire [7:0]       out_r,
    output wire [7:0]       out_g,
    output wire [7:0]       out_b
);

    // AP-10K 17-edge topology matching board/test_pose.cpp
    function integer edge_idx_a;
        input integer e;
        begin
            case (e)
                0:  edge_idx_a = 13; 1:  edge_idx_a = 12; 2:  edge_idx_a = 11;
                3:  edge_idx_a = 16; 4:  edge_idx_a = 15; 5:  edge_idx_a = 14;
                6:  edge_idx_a = 4;  7:  edge_idx_a = 3;  8:  edge_idx_a = 5;
                9:  edge_idx_a = 6;  10: edge_idx_a = 3;  11: edge_idx_a = 8;
                12: edge_idx_a = 9;  13: edge_idx_a = 3;  14: edge_idx_a = 0;
                15: edge_idx_a = 2;  16: edge_idx_a = 2;
                default: edge_idx_a = 0;
            endcase
        end
    endfunction

    function integer edge_idx_b;
        input integer e;
        begin
            case (e)
                0:  edge_idx_b = 12; 1:  edge_idx_b = 11; 2:  edge_idx_b = 4;
                3:  edge_idx_b = 15; 4:  edge_idx_b = 14; 5:  edge_idx_b = 4;
                6:  edge_idx_b = 3;  7:  edge_idx_b = 5;  8:  edge_idx_b = 6;
                9:  edge_idx_b = 7;  10: edge_idx_b = 8;  11: edge_idx_b = 9;
                12: edge_idx_b = 10; 13: edge_idx_b = 2;  14: edge_idx_b = 1;
                15: edge_idx_b = 0;  16: edge_idx_b = 1;
                default: edge_idx_b = 0;
            endcase
        end
    endfunction

    (* ASYNC_REG = "TRUE" *) reg [2:0] commit_sync;
    reg commit_pending;

    reg [10:0] act_x1, act_x2;
    reg [9:0]  act_y1, act_y2;
    reg        act_valid;
    reg [1:0]  act_label; // 1=CAT, 2=DOG
    reg [1:0]  act_pose;  // 0=UNK, 1=STD, 2=SIT, 3=LIE
    reg [10:0] act_kpt_x [0:16];
    reg [9:0]  act_kpt_y [0:16];
    reg [16:0] act_kpt_valid;

    integer k;

    always @(posedge pixel_clk or posedge pixel_reset) begin
        if (pixel_reset) begin
            commit_sync    <= 3'b000;
            commit_pending <= 1'b0;
            act_x1         <= 11'd0;
            act_y1         <= 10'd0;
            act_x2         <= 11'd0;
            act_y2         <= 10'd0;
            act_valid      <= 1'b0;
            act_label      <= 2'd0;
            act_pose       <= 2'd0;
            act_kpt_valid  <= 17'd0;
            for (k = 0; k < 17; k = k + 1) begin
                act_kpt_x[k] <= 11'd0;
                act_kpt_y[k] <= 10'd0;
            end
        end else begin
            commit_sync <= {commit_sync[1:0], sh_commit_toggle};
            if (commit_sync[2] ^ commit_sync[1])
                commit_pending <= 1'b1;

            if (vs_frame_start && (commit_pending || (commit_sync[2] ^ commit_sync[1]))) begin
                commit_pending <= 1'b0;
                act_x1         <= sh_x1;
                act_y1         <= sh_y1;
                act_x2         <= sh_x2;
                act_y2         <= sh_y2;
                act_valid      <= sh_valid;
                act_label      <= sh_label;
                act_pose       <= sh_pose;
                act_kpt_valid  <= sh_kpt_valid;
                for (k = 0; k < 17; k = k + 1) begin
                    act_kpt_x[k] <= sh_kpt_x_flat[k*11 +: 11];
                    act_kpt_y[k] <= sh_kpt_y_flat[k*10 +: 10];
                end
            end
        end
    end

    // 3-pixel thick bounding box check (combinational stage 0)
    wire in_box_x = (pixel_x >= act_x1) && (pixel_x <= act_x2);
    wire in_box_y = (pixel_y >= act_y1) && (pixel_y <= act_y2);
    wire on_border = act_valid && in_box_x && in_box_y && (
        (pixel_x - act_x1 < 11'd3) || (act_x2 - pixel_x < 11'd3) ||
        (pixel_y - act_y1 < 10'd3) || (act_y2 - pixel_y < 10'd3)
    );

    // 2x scaled 8x8 label ("CAT-STD" / "DOG-SIT" / etc.) -> 112x16 tag inside/above top-left of box
    wire [9:0]  tag_y0 = (act_y1 >= 10'd18) ? (act_y1 - 10'd18) : act_y1;
    wire [10:0] tag_x0 = (act_x1 <= 11'd1167) ? act_x1 : 11'd1167;
    wire in_tag = act_valid && (act_label == 2'd1 || act_label == 2'd2) &&
                  (pixel_x >= tag_x0) && (pixel_x < tag_x0 + 11'd112) &&
                  (pixel_y >= tag_y0) && (pixel_y < tag_y0 + 10'd16);

    wire [10:0] rel_x_full = pixel_x - tag_x0;
    wire [9:0]  rel_y_full = pixel_y - tag_y0;
    wire [6:0]  rel_x = rel_x_full[6:0];
    wire [3:0]  rel_y = rel_y_full[3:0];
    wire [2:0]  ch_idx  = rel_x[6:4];
    wire [2:0]  col_idx = rel_x[3:1];
    wire [2:0]  row_idx = rel_y[3:1];

    localparam [3:0]
        CH_SPC = 4'd0,  CH_C = 4'd1,  CH_A = 4'd2,  CH_T = 4'd3,
        CH_D   = 4'd4,  CH_O = 4'd5,  CH_G = 4'd6,  CH_DASH = 4'd7,
        CH_U   = 4'd8,  CH_N = 4'd9,  CH_K = 4'd10, CH_S = 4'd11,
        CH_I   = 4'd12, CH_L = 4'd13, CH_E = 4'd14;

    function [7:0] glyph_row;
        input [3:0] ch;
        input [2:0] r;
        begin
            glyph_row = 8'h00;
            case (ch)
                CH_C: case (r)
                    3'd0, 3'd6: glyph_row = 8'b00111100;
                    3'd1, 3'd5: glyph_row = 8'b01100110;
                    3'd2, 3'd3, 3'd4: glyph_row = 8'b01100000;
                    default: glyph_row = 8'h00;
                endcase
                CH_A: case (r)
                    3'd0: glyph_row = 8'b00011000;
                    3'd1: glyph_row = 8'b00111100;
                    3'd2, 3'd4, 3'd5, 3'd6: glyph_row = 8'b01100110;
                    3'd3: glyph_row = 8'b01111110;
                    default: glyph_row = 8'h00;
                endcase
                CH_T: case (r)
                    3'd0: glyph_row = 8'b01111110;
                    3'd1, 3'd2, 3'd3, 3'd4, 3'd5, 3'd6: glyph_row = 8'b00011000;
                    default: glyph_row = 8'h00;
                endcase
                CH_D: case (r)
                    3'd0, 3'd6: glyph_row = 8'b01111100;
                    3'd1, 3'd2, 3'd3, 3'd4, 3'd5: glyph_row = 8'b01100110;
                    default: glyph_row = 8'h00;
                endcase
                CH_O: case (r)
                    3'd0, 3'd6: glyph_row = 8'b00111100;
                    3'd1, 3'd2, 3'd3, 3'd4, 3'd5: glyph_row = 8'b01100110;
                    default: glyph_row = 8'h00;
                endcase
                CH_G: case (r)
                    3'd0, 3'd6: glyph_row = 8'b00111100;
                    3'd1, 3'd4, 3'd5: glyph_row = 8'b01100110;
                    3'd2: glyph_row = 8'b01100000;
                    3'd3: glyph_row = 8'b01101110;
                    default: glyph_row = 8'h00;
                endcase
                CH_DASH: glyph_row = (r == 3'd3) ? 8'b00111100 : 8'h00;
                CH_U: case (r)
                    3'd0, 3'd1, 3'd2, 3'd3, 3'd4, 3'd5: glyph_row = 8'b01100110;
                    3'd6: glyph_row = 8'b00111100;
                    default: glyph_row = 8'h00;
                endcase
                CH_N: case (r)
                    3'd0, 3'd4, 3'd5, 3'd6: glyph_row = 8'b01100110;
                    3'd1: glyph_row = 8'b01110110;
                    3'd2: glyph_row = 8'b01111110;
                    3'd3: glyph_row = 8'b01101110;
                    default: glyph_row = 8'h00;
                endcase
                CH_K: case (r)
                    3'd0, 3'd6: glyph_row = 8'b01100110;
                    3'd1, 3'd5: glyph_row = 8'b01101100;
                    3'd2, 3'd4: glyph_row = 8'b01111000;
                    3'd3: glyph_row = 8'b01110000;
                    default: glyph_row = 8'h00;
                endcase
                CH_S: case (r)
                    3'd0, 3'd3, 3'd6: glyph_row = 8'b00111100;
                    3'd1, 3'd5: glyph_row = 8'b01100110;
                    3'd2: glyph_row = 8'b01100000;
                    3'd4: glyph_row = 8'b00000110;
                    default: glyph_row = 8'h00;
                endcase
                CH_I: case (r)
                    3'd0, 3'd6: glyph_row = 8'b00111100;
                    3'd1, 3'd2, 3'd3, 3'd4, 3'd5: glyph_row = 8'b00011000;
                    default: glyph_row = 8'h00;
                endcase
                CH_L: case (r)
                    3'd0, 3'd1, 3'd2, 3'd3, 3'd4, 3'd5: glyph_row = 8'b01100000;
                    3'd6: glyph_row = 8'b01111110;
                    default: glyph_row = 8'h00;
                endcase
                CH_E: case (r)
                    3'd0, 3'd6: glyph_row = 8'b01111110;
                    3'd1, 3'd2, 3'd4, 3'd5: glyph_row = 8'b01100000;
                    3'd3: glyph_row = 8'b01111100;
                    default: glyph_row = 8'h00;
                endcase
                default: glyph_row = 8'h00;
            endcase
        end
    endfunction

    reg [3:0] cur_ch;
    always @(*) begin
        cur_ch = CH_SPC;
        case (ch_idx)
            3'd0: cur_ch = (act_label == 2'd1) ? CH_C : CH_D;
            3'd1: cur_ch = (act_label == 2'd1) ? CH_A : CH_O;
            3'd2: cur_ch = (act_label == 2'd1) ? CH_T : CH_G;
            3'd3: cur_ch = CH_DASH;
            3'd4: case (act_pose)
                2'd1: cur_ch = CH_S; // STD
                2'd2: cur_ch = CH_S; // SIT
                2'd3: cur_ch = CH_L; // LIE
                default: cur_ch = CH_U; // UNK
            endcase
            3'd5: case (act_pose)
                2'd1: cur_ch = CH_T;
                2'd2: cur_ch = CH_I;
                2'd3: cur_ch = CH_I;
                default: cur_ch = CH_N;
            endcase
            3'd6: case (act_pose)
                2'd1: cur_ch = CH_D;
                2'd2: cur_ch = CH_T;
                2'd3: cur_ch = CH_E;
                default: cur_ch = CH_K;
            endcase
            default: cur_ch = CH_SPC;
        endcase
    end

    wire [7:0] font_row = glyph_row(cur_ch, row_idx);
    wire       font_fg  = font_row[3'd7 - col_idx];

    // 17 green joint dots (7x7 octagon: |dx|<=3, |dy|<=3, |dx|+|dy|<=4)
    wire [16:0] joint_hits;
    genvar gj;
    generate
        for (gj = 0; gj < 17; gj = gj + 1) begin : g_joints
            wire [10:0] j_dx = (pixel_x >= act_kpt_x[gj]) ? (pixel_x - act_kpt_x[gj]) : (act_kpt_x[gj] - pixel_x);
            wire [9:0]  j_dy = (pixel_y >= act_kpt_y[gj]) ? (pixel_y - act_kpt_y[gj]) : (act_kpt_y[gj] - pixel_y);
            assign joint_hits[gj] = act_kpt_valid[gj] &&
                                    (j_dx <= 11'd3) && (j_dy <= 10'd3) &&
                                    (({1'b0, j_dx} + {2'b0, j_dy}) <= 12'd4);
        end
    endgenerate
    wire on_joint_s0 = |joint_hits;

    // 17 skeleton edges: 2-stage streaming check
    // Stage 1 (registered): compute dx*(py-y0), dy*(px-x0), bounding box enable, and threshold
    // Stage 2 (combinational -> external hdmi_r FF): |prod_a - prod_b| <= 1.5*max(|dx|,|dy|)
    reg        p1_hs, p1_vs, p1_de;
    reg [7:0]  p1_r, p1_g, p1_b;
    reg        p1_on_border, p1_in_tag, p1_font_fg, p1_on_joint;
    reg [1:0]  p1_act_label;

    wire [16:0] edge_hits;
    genvar ge;
    generate
        for (ge = 0; ge < 17; ge = ge + 1) begin : g_edges
            localparam integer EA = edge_idx_a(ge);
            localparam integer EB = edge_idx_b(ge);

            wire [10:0] x0 = act_kpt_x[EA];
            wire [9:0]  y0 = act_kpt_y[EA];
            wire [10:0] x1 = act_kpt_x[EB];
            wire [9:0]  y1 = act_kpt_y[EB];

            wire signed [11:0] dx = $signed({1'b0, x1}) - $signed({1'b0, x0});
            wire signed [11:0] dy = $signed({2'b0, y1}) - $signed({2'b0, y0});
            wire [11:0] abs_dx = dx[11] ? (~dx + 12'd1) : dx;
            wire [11:0] abs_dy = dy[11] ? (~dy + 12'd1) : dy;
            wire [10:0] max_d  = (abs_dx >= abs_dy) ? abs_dx[10:0] : abs_dy[10:0];
            wire [11:0] thresh = {1'b0, max_d} + {2'b0, max_d[10:1]}; // 1.5 * max(|dx|,|dy|)

            wire [10:0] min_x = (x0 < x1) ? x0 : x1;
            wire [10:0] max_x = (x0 < x1) ? x1 : x0;
            wire [9:0]  min_y = (y0 < y1) ? y0 : y1;
            wire [9:0]  max_y = (y0 < y1) ? y1 : y0;

            wire in_bbox = act_kpt_valid[EA] && act_kpt_valid[EB] &&
                           ({1'b0, pixel_x} + 12'd2 >= {1'b0, min_x}) &&
                           ({1'b0, pixel_x} <= {1'b0, max_x} + 12'd2) &&
                           ({1'b0, pixel_y} + 11'd2 >= {1'b0, min_y}) &&
                           ({1'b0, pixel_y} <= {1'b0, max_y} + 11'd2);

            wire signed [11:0] px_off = $signed({1'b0, pixel_x}) - $signed({1'b0, x0});
            wire signed [11:0] py_off = $signed({2'b0, pixel_y}) - $signed({2'b0, y0});

            reg signed [23:0] p1_prod_a;
            reg signed [23:0] p1_prod_b;
            reg        [11:0] p1_thresh;
            reg               p1_edge_en;

            always @(posedge pixel_clk or posedge pixel_reset) begin
                if (pixel_reset) begin
                    p1_prod_a  <= 24'sd0;
                    p1_prod_b  <= 24'sd0;
                    p1_thresh  <= 12'd0;
                    p1_edge_en <= 1'b0;
                end else begin
                    p1_prod_a  <= dx * py_off;
                    p1_prod_b  <= dy * px_off;
                    p1_thresh  <= thresh;
                    p1_edge_en <= in_bbox;
                end
            end

            wire signed [23:0] cross_diff = p1_prod_a - p1_prod_b;
            wire [23:0] cross_abs = cross_diff[23] ? (~cross_diff + 24'd1) : cross_diff;
            assign edge_hits[ge] = p1_edge_en && (cross_abs <= {12'd0, p1_thresh});
        end
    endgenerate

    always @(posedge pixel_clk or posedge pixel_reset) begin
        if (pixel_reset) begin
            p1_hs        <= 1'b0;
            p1_vs        <= 1'b0;
            p1_de        <= 1'b0;
            p1_r         <= 8'd0;
            p1_g         <= 8'd0;
            p1_b         <= 8'd0;
            p1_on_border <= 1'b0;
            p1_in_tag    <= 1'b0;
            p1_font_fg   <= 1'b0;
            p1_on_joint  <= 1'b0;
            p1_act_label <= 2'd0;
        end else begin
            p1_hs        <= in_hs;
            p1_vs        <= in_vs;
            p1_de        <= de;
            p1_r         <= in_r;
            p1_g         <= in_g;
            p1_b         <= in_b;
            p1_on_border <= on_border;
            p1_in_tag    <= in_tag;
            p1_font_fg   <= font_fg;
            p1_on_joint  <= on_joint_s0;
            p1_act_label <= act_label;
        end
    end

    wire on_skel_line = |edge_hits;

    // CAT = bright green (0,255,0), DOG box = yellow (255,255,0), joints = bright lime-green (128,255,0), skeleton lines = pure green (0,255,0)
    wire [7:0] box_r = (p1_act_label == 2'd2) ? 8'hff : 8'h00;
    wire [7:0] box_g = 8'hff;
    wire [7:0] box_b = 8'h00;

    assign out_hs = p1_hs;
    assign out_vs = p1_vs;
    assign out_de = p1_de;

    assign out_r = !p1_de       ? 8'h00 :
                   p1_on_joint  ? 8'h80 :
                   on_skel_line ? 8'h00 :
                   p1_on_border ? box_r :
                   p1_in_tag    ? (p1_font_fg ? 8'h00 : box_r) : p1_r;

    assign out_g = !p1_de       ? 8'h00 :
                   p1_on_joint  ? 8'hff :
                   on_skel_line ? 8'hff :
                   p1_on_border ? box_g :
                   p1_in_tag    ? (p1_font_fg ? 8'h00 : box_g) : p1_g;

    assign out_b = !p1_de       ? 8'h00 :
                   p1_on_joint  ? 8'h00 :
                   on_skel_line ? 8'h00 :
                   p1_on_border ? box_b :
                   p1_in_tag    ? (p1_font_fg ? 8'h00 : box_b) : p1_b;

endmodule
