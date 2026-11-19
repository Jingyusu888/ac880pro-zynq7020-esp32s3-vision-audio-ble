`timescale 1ns/1ps
// Captures one 256x144 RGB565 thumbnail (every 5th pixel, every 5th line from
// 1280x720 DVP stream) into a 32-bit byte-addressed BRAM port on PS request.
// Holds lock until PS acknowledges copy via release toggle.
module petlink_mailbox_capture #(
    parameter SRC_WIDTH  = 1280,
    parameter SRC_HEIGHT = 720,
    parameter STEP       = 5
)(
    // AXI clock domain (100 MHz)
    input  wire        axi_clk,
    input  wire        axi_resetn,
    input  wire        cmd_req,
    input  wire        cmd_release,
    output reg         status_busy,
    output reg         status_ready,
    output reg  [15:0] frame_seq,
    output reg  [15:0] last_pix_cnt,

    // Camera pixel clock domain
    input  wire        pclk,
    input  wire        pclk_reset,
    input  wire        cam_sof,
    input  wire        cam_href,
    input  wire        cam_pv,
    input  wire [15:0] cam_pd,

    // True Dual-Port BRAM Port B (32-bit, byte-addressed to match axi_bram_ctrl)
    output reg  [31:0] bram_addr,
    output reg  [31:0] bram_din,
    output reg  [3:0]  bram_we,
    output wire        bram_en,
    output wire        bram_rst
);

    localparam TOTAL_THUMB_PIX = (SRC_WIDTH / STEP) * (SRC_HEIGHT / STEP); // 256*144 = 36864

    assign bram_en  = 1'b1;
    assign bram_rst = 1'b0;

    // -------------------------------------------------------------------------
    // AXI domain: request / release toggle generation & done synchronization
    // -------------------------------------------------------------------------
    reg req_toggle;
    reg rel_toggle;

    (* ASYNC_REG = "TRUE" *) reg [2:0] done_sync_axi;
    reg done_toggle_pclk;
    reg [15:0] pix_cnt_pclk;

    always @(posedge axi_clk or negedge axi_resetn) begin
        if (!axi_resetn) begin
            req_toggle    <= 1'b0;
            rel_toggle    <= 1'b0;
            done_sync_axi <= 3'b000;
            status_busy   <= 1'b0;
            status_ready  <= 1'b0;
            frame_seq     <= 16'd0;
            last_pix_cnt  <= 16'd0;
        end else begin
            done_sync_axi <= {done_sync_axi[1:0], done_toggle_pclk};

            // Detect capture completion from pclk domain
            if (done_sync_axi[2] ^ done_sync_axi[1]) begin
                status_busy  <= 1'b0;
                status_ready <= 1'b1;
                frame_seq    <= frame_seq + 16'd1;
                last_pix_cnt <= pix_cnt_pclk;
            end else if (cmd_release && status_ready) begin
                status_ready <= 1'b0;
                rel_toggle   <= ~rel_toggle;
            end else if (cmd_req && !status_busy && !status_ready) begin
                status_busy <= 1'b1;
                req_toggle  <= ~req_toggle;
            end
        end
    end

    // -------------------------------------------------------------------------
    // PCLK domain: synchronizers and capture state machine
    // -------------------------------------------------------------------------
    (* ASYNC_REG = "TRUE" *) reg [2:0] req_sync_pclk;
    (* ASYNC_REG = "TRUE" *) reg [2:0] rel_sync_pclk;

    localparam P_IDLE      = 2'd0,
               P_ARMED     = 2'd1,
               P_CAPTURING = 2'd2,
               P_LOCKED    = 2'd3;

    reg [1:0]  p_state;
    reg [10:0] x_cnt;
    reg [9:0]  y_cnt;
    reg [2:0]  x_mod5;
    reg [2:0]  y_mod5;
    reg        href_d;
    reg [14:0] word_idx;
    reg        half_pix;
    reg [15:0] low_pix;

    wire req_edge = req_sync_pclk[2] ^ req_sync_pclk[1];
    wire rel_edge = rel_sync_pclk[2] ^ rel_sync_pclk[1];

    always @(posedge pclk or posedge pclk_reset) begin
        if (pclk_reset) begin
            req_sync_pclk    <= 3'b000;
            rel_sync_pclk    <= 3'b000;
            p_state          <= P_IDLE;
            done_toggle_pclk <= 1'b0;
            pix_cnt_pclk     <= 16'd0;
            x_cnt            <= 11'd0;
            y_cnt            <= 10'd0;
            x_mod5           <= 3'd0;
            y_mod5           <= 3'd0;
            href_d           <= 1'b0;
            word_idx         <= 15'd0;
            half_pix         <= 1'b0;
            low_pix          <= 16'd0;
            bram_addr        <= 32'd0;
            bram_din         <= 32'd0;
            bram_we          <= 4'b0000;
        end else begin
            req_sync_pclk <= {req_sync_pclk[1:0], req_toggle};
            rel_sync_pclk <= {rel_sync_pclk[1:0], rel_toggle};
            href_d        <= cam_href;
            bram_we       <= 4'b0000;

            case (p_state)
                P_IDLE: begin
                    if (req_edge)
                        p_state <= P_ARMED;
                end

                P_ARMED: begin
                    if (cam_sof) begin
                        p_state      <= P_CAPTURING;
                        x_cnt        <= 11'd0;
                        y_cnt        <= 10'd0;
                        x_mod5       <= 3'd0;
                        y_mod5       <= 3'd0;
                        word_idx     <= 15'd0;
                        half_pix     <= 1'b0;
                        pix_cnt_pclk <= 16'd0;
                    end
                end

                P_CAPTURING: begin
                    // Premature SOF restarts clean frame capture
                    if (cam_sof) begin
                        x_cnt        <= 11'd0;
                        y_cnt        <= 10'd0;
                        x_mod5       <= 3'd0;
                        y_mod5       <= 3'd0;
                        word_idx     <= 15'd0;
                        half_pix     <= 1'b0;
                        pix_cnt_pclk <= 16'd0;
                    end else begin
                        if (cam_pv && (x_cnt < SRC_WIDTH) && (y_cnt < SRC_HEIGHT)) begin
                            if (x_mod5 == 3'd0 && y_mod5 == 3'd0) begin
                                pix_cnt_pclk <= pix_cnt_pclk + 16'd1;
                                if (!half_pix) begin
                                    low_pix  <= cam_pd;
                                    half_pix <= 1'b1;
                                end else begin
                                    bram_addr <= {15'd0, word_idx, 2'b00};
                                    bram_din  <= {cam_pd, low_pix};
                                    bram_we   <= 4'b1111;
                                    word_idx  <= word_idx + 15'd1;
                                    half_pix  <= 1'b0;
                                    if (pix_cnt_pclk + 16'd1 == TOTAL_THUMB_PIX) begin
                                        done_toggle_pclk <= ~done_toggle_pclk;
                                        p_state          <= P_LOCKED;
                                    end
                                end
                            end

                            if (x_cnt == SRC_WIDTH - 1) begin
                                x_cnt  <= 11'd0;
                                x_mod5 <= 3'd0;
                                y_cnt  <= y_cnt + 10'd1;
                                y_mod5 <= (y_mod5 == STEP - 1) ? 3'd0 : (y_mod5 + 3'd1);
                            end else begin
                                x_cnt  <= x_cnt + 11'd1;
                                x_mod5 <= (x_mod5 == STEP - 1) ? 3'd0 : (x_mod5 + 3'd1);
                            end
                        end else if (href_d && !cam_href && (x_cnt != 11'd0)) begin
                            // Line ended early; advance row cleanly so next line stays aligned
                            x_cnt  <= 11'd0;
                            x_mod5 <= 3'd0;
                            y_cnt  <= y_cnt + 10'd1;
                            y_mod5 <= (y_mod5 == STEP - 1) ? 3'd0 : (y_mod5 + 3'd1);
                        end
                    end
                end

                P_LOCKED: begin
                    // Never touch BRAM until PS confirms copy and releases buffer
                    if (rel_edge)
                        p_state <= P_IDLE;
                end

                default: p_state <= P_IDLE;
            endcase
        end
    end

endmodule
