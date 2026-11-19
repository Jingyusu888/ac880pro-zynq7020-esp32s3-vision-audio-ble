`timescale 1ns/1ps

module tb_petlink_bridge;
    reg axi_clk = 0;
    always #5 axi_clk = ~axi_clk; // 100 MHz

    reg pclk = 0;
    always #11 pclk = ~pclk; // ~45.45 MHz async to axi_clk

    reg pixel_clk = 0;
    always #6.737 pixel_clk = ~pixel_clk; // ~74.22 MHz

    reg axi_resetn = 0;
    reg pclk_reset = 1;
    reg pixel_reset = 1;

    // AXI4-Lite wires
    reg  [7:0]  awaddr = 0;
    reg         awvalid = 0;
    wire        awready;
    reg  [31:0] wdata = 0;
    reg  [3:0]  wstrb = 4'hF;
    reg         wvalid = 0;
    wire        wready;
    wire [1:0]  bresp;
    wire        bvalid;
    reg         bready = 1;
    reg  [7:0]  araddr = 0;
    reg         arvalid = 0;
    wire        arready;
    wire [31:0] rdata;
    wire [1:0]  rresp;
    wire        rvalid;
    reg         rready = 1;

    wire cmd_req, cmd_release, status_busy, status_ready;
    wire [15:0] frame_seq, last_pix_cnt;
    wire [10:0] box_x1, box_x2;
    wire [9:0]  box_y1, box_y2;
    wire        box_valid, box_commit_toggle;
    wire [1:0]  box_label, box_pose;
    wire [17*11-1:0] kpt_x_flat;
    wire [17*10-1:0] kpt_y_flat;
    wire [16:0]      kpt_valid;

    petlink_ctrl_regs dut_regs(
        .s_axi_aclk(axi_clk), .s_axi_aresetn(axi_resetn),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .cmd_req(cmd_req), .cmd_release(cmd_release),
        .status_busy(status_busy), .status_ready(status_ready),
        .frame_seq(frame_seq), .last_pix_cnt(last_pix_cnt),
        .box_x1(box_x1), .box_y1(box_y1), .box_x2(box_x2), .box_y2(box_y2),
        .box_valid(box_valid), .box_label(box_label), .box_pose(box_pose), .box_commit_toggle(box_commit_toggle),
        .kpt_x_flat(kpt_x_flat), .kpt_y_flat(kpt_y_flat), .kpt_valid(kpt_valid)
    );

    reg cam_sof = 0, cam_href = 0, cam_pv = 0;
    reg [15:0] cam_pd = 0;
    wire [31:0] bram_addr, bram_din;
    wire [3:0]  bram_we;
    wire        bram_en, bram_rst;

    petlink_mailbox_capture dut_cap(
        .axi_clk(axi_clk), .axi_resetn(axi_resetn),
        .cmd_req(cmd_req), .cmd_release(cmd_release),
        .status_busy(status_busy), .status_ready(status_ready),
        .frame_seq(frame_seq), .last_pix_cnt(last_pix_cnt),
        .pclk(pclk), .pclk_reset(pclk_reset),
        .cam_sof(cam_sof), .cam_href(cam_href), .cam_pv(cam_pv), .cam_pd(cam_pd),
        .bram_addr(bram_addr), .bram_din(bram_din), .bram_we(bram_we),
        .bram_en(bram_en), .bram_rst(bram_rst)
    );

    // Behavioral BRAM model (18432 words = 73728 bytes)
    reg [31:0] bram_mem [0:18431];
    always @(posedge pclk) begin
        if (bram_en && bram_we == 4'b1111) begin
            if ((bram_addr >> 2) < 18432)
                bram_mem[bram_addr >> 2] <= bram_din;
        end
    end

    // OSD under test
    reg vs_frame_start = 0, in_hs = 0, in_vs = 0, de = 0;
    reg [10:0] px = 0;
    reg [9:0]  py = 0;
    wire out_hs, out_vs, out_de;
    wire [7:0] out_r, out_g, out_b;

    petlink_osd dut_osd(
        .pixel_clk(pixel_clk), .pixel_reset(pixel_reset),
        .vs_frame_start(vs_frame_start),
        .in_hs(in_hs), .in_vs(in_vs), .de(de),
        .pixel_x(px), .pixel_y(py),
        .in_r(8'h10), .in_g(8'h20), .in_b(8'h30),
        .sh_x1(box_x1), .sh_y1(box_y1), .sh_x2(box_x2), .sh_y2(box_y2),
        .sh_valid(box_valid), .sh_label(box_label), .sh_pose(box_pose), .sh_commit_toggle(box_commit_toggle),
        .sh_kpt_x_flat(kpt_x_flat), .sh_kpt_y_flat(kpt_y_flat), .sh_kpt_valid(kpt_valid),
        .out_hs(out_hs), .out_vs(out_vs), .out_de(out_de),
        .out_r(out_r), .out_g(out_g), .out_b(out_b)
    );

    task axi_write(input [7:0] addr, input [31:0] val);
    begin
        @(posedge axi_clk);
        awaddr <= addr; awvalid <= 1'b1;
        wdata  <= val;  wvalid  <= 1'b1;
        wait (awready && wready);
        @(posedge axi_clk);
        awvalid <= 1'b0; wvalid <= 1'b0;
        wait (bvalid);
        @(posedge axi_clk);
    end
    endtask

    task axi_read(input [7:0] addr, output [31:0] val);
    begin
        @(posedge axi_clk);
        araddr <= addr; arvalid <= 1'b1;
        wait (arready);
        @(posedge axi_clk);
        arvalid <= 1'b0;
        wait (rvalid);
        val = rdata;
        @(posedge axi_clk);
    end
    endtask

    task send_frame(input [7:0] tag, input integer lines);
        integer y, x;
    begin
        @(posedge pclk);
        cam_sof <= 1'b1;
        @(posedge pclk);
        cam_sof <= 1'b0;
        for (y = 0; y < lines; y = y + 1) begin
            @(posedge pclk);
            cam_href <= 1'b1;
            for (x = 0; x < 1280; x = x + 1) begin
                cam_pv <= 1'b1;
                cam_pd <= {tag, x[3:0], y[3:0]};
                @(posedge pclk);
            end
            cam_pv   <= 1'b0;
            cam_href <= 1'b0;
            repeat (4) @(posedge pclk);
        end
    end
    endtask

    reg [31:0] rval;
    integer err_cnt = 0;

    initial begin
        #100;
        axi_resetn = 1'b1;
        pclk_reset = 1'b0;
        pixel_reset = 1'b0;
        #100;

        // 1. Check magic ID
        axi_read(6'h00, rval);
        if (rval !== 32'hAC88_0720) begin
            $display("FAIL: MAGIC_ID=%h", rval);
            err_cnt = err_cnt + 1;
        end else $display("PASS: MAGIC_ID=%h", rval);

        // 2. Request frame, allow CDC sync (~5 pclk), then send full 1280x720 frame
        axi_write(6'h04, 32'h1); // CAPTURE_REQ
        repeat (6) @(posedge pclk);
        send_frame(8'hA5, 720);
        repeat (20) @(posedge axi_clk);

        axi_read(6'h08, rval);
        if (rval[1] !== 1'b1 || rval[31:16] !== 16'd1) begin
            $display("FAIL: STATUS after frame1=%h", rval);
            err_cnt = err_cnt + 1;
        end
        axi_read(6'h0C, rval);
        if (rval !== 32'd36864) begin
            $display("FAIL: PIX_CNT=%d", rval);
            err_cnt = err_cnt + 1;
        end else $display("PASS: Captured 36864 pixels, locked!");

        // Verify word 0: pixel(0,0) and pixel(5,0) with tag 0xA5
        if (bram_mem[0] !== {8'hA5, 4'd5, 4'd0, 8'hA5, 4'd0, 4'd0}) begin
            $display("FAIL: bram_mem[0]=%h", bram_mem[0]);
            err_cnt = err_cnt + 1;
        end
        // Verify last word (18431): pixel(1270,715) and pixel(1275,715)
        if (bram_mem[18431] !== {8'hA5, 4'd11, 4'd11, 8'hA5, 4'd6, 4'd11}) begin
            $display("FAIL: bram_mem[18431]=%h", bram_mem[18431]);
            err_cnt = err_cnt + 1;
        end

        // 3. Send another frame while locked -> must NOT overwrite BRAM!
        send_frame(8'h5A, 720);
        if (bram_mem[0] !== {8'hA5, 4'd5, 4'd0, 8'hA5, 4'd0, 4'd0}) begin
            $display("FAIL: BRAM overwritten while locked! %h", bram_mem[0]);
            err_cnt = err_cnt + 1;
        end else $display("PASS: BRAM lock held against overwrite");

        // 4. Release, request again, send premature SOF after 10 lines, then full frame
        axi_write(6'h04, 32'h2); // CAPTURE_RELEASE
        repeat (10) @(posedge axi_clk);
        axi_write(6'h04, 32'h1); // CAPTURE_REQ
        send_frame(8'h11, 10);   // truncated frame
        send_frame(8'hB2, 720);  // clean full frame
        repeat (20) @(posedge axi_clk);
        axi_read(6'h08, rval);
        if (rval[1] !== 1'b1 || rval[31:16] !== 16'd2 || bram_mem[0] !== {8'hB2, 4'd5, 4'd0, 8'hB2, 4'd0, 4'd0}) begin
            $display("FAIL: Recovery frame2 status=%h word0=%h", rval, bram_mem[0]);
            err_cnt = err_cnt + 1;
        end else $display("PASS: Premature SOF recovery & frame2 OK");

        // 5. OSD test: set CAT box (100,100)-(200,200), commit, check before/after vsync
        axi_write(8'h10, {6'd0, 10'd100, 5'd0, 11'd100});
        axi_write(8'h14, {6'd0, 10'd200, 5'd0, 11'd200});
        axi_write(8'h18, 32'b011); // label=1(CAT), valid=1
        axi_write(8'h04, 32'h4);   // OSD_COMMIT
        repeat (10) @(posedge pixel_clk);
        // Before vsync: should pass through background (0x10, 0x20, 0x30) (1-cycle pipeline)
        de <= 1'b1; px <= 11'd100; py <= 10'd100;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_de !== 1'b1 || out_r !== 8'h10 || out_g !== 8'h20) begin
            $display("FAIL: OSD updated before vsync! de=%b rgb=%h %h %h", out_de, out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end
        // Pulse vsync
        @(posedge pixel_clk); vs_frame_start <= 1'b1;
        @(posedge pixel_clk); vs_frame_start <= 1'b0;
        repeat (2) @(posedge pixel_clk); #1;
        if (out_r !== 8'h00 || out_g !== 8'hFF || out_b !== 8'h00) begin
            $display("FAIL: OSD CAT border expected green, got %h %h %h", out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end else $display("PASS: OSD boundary latching & green box OK");

        // 6. Step 54 & 55 Skeleton test: joints 0=(300,200), 1=(420,260), 2=(500,300), invalid 3=(700,400)
        // Edge 14 connects {0, 1}; Edge 13 connects {3, 2} (must NOT draw since kpt 3 invalid!)
        axi_write(8'h20, {6'd0, 10'd200, 5'd0, 11'd300}); // KPT[0]
        axi_write(8'h24, {6'd0, 10'd260, 5'd0, 11'd420}); // KPT[1]
        axi_write(8'h28, {6'd0, 10'd300, 5'd0, 11'd500}); // KPT[2]
        axi_write(8'h2C, {6'd0, 10'd400, 5'd0, 11'd700}); // KPT[3]
        axi_write(8'h1C, 32'h0000_0007); // bits 0,1,2 valid; bit 3 invalid
        axi_read(8'h1C, rval);
        if (rval !== 32'h0000_0007) begin
            $display("FAIL: KPT_VALID readback=%h", rval); err_cnt = err_cnt + 1;
        end
        axi_read(8'h24, rval);
        if (rval !== {6'd0, 10'd260, 5'd0, 11'd420}) begin
            $display("FAIL: KPT[1] readback=%h", rval); err_cnt = err_cnt + 1;
        end
        axi_write(8'h04, 32'h4); // OSD_COMMIT
        repeat (10) @(posedge pixel_clk);
        @(posedge pixel_clk); vs_frame_start <= 1'b1;
        @(posedge pixel_clk); vs_frame_start <= 1'b0;

        // 6a. Joint dot center (300,200) -> bright lime-green (0x80, 0xFF, 0x00)
        @(posedge pixel_clk); de <= 1'b1; in_hs <= 1'b1; in_vs <= 1'b0; px <= 11'd300; py <= 10'd200;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_hs !== 1'b1 || out_de !== 1'b1 || out_r !== 8'h80 || out_g !== 8'hFF || out_b !== 8'h00) begin
            $display("FAIL: Joint 0 dot got hs=%b de=%b rgb=%h %h %h", out_hs, out_de, out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end else $display("PASS: Joint 0 green dot & pipeline sync OK");

        // 6b. Diagonal edge {0,1} midpoint (360,230) -> pure green line (0x00, 0xFF, 0x00)
        @(posedge pixel_clk); in_hs <= 1'b0; px <= 11'd360; py <= 10'd230;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_hs !== 1'b0 || out_r !== 8'h00 || out_g !== 8'hFF || out_b !== 8'h00) begin
            $display("FAIL: Edge {0,1} midpoint expected green line, got hs=%b rgb=%h %h %h", out_hs, out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end else $display("PASS: Diagonal edge {0,1} streaming green line OK");

        // 6c. Off-line pixel (360,250) -> background (0x10, 0x20, 0x30)
        @(posedge pixel_clk); px <= 11'd360; py <= 10'd250;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_r !== 8'h10 || out_g !== 8'h20 || out_b !== 8'h30) begin
            $display("FAIL: Off-line pixel expected bg, got %h %h %h", out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end

        // 6d. Invalid joint 3 center (700,400) -> hidden (background)
        @(posedge pixel_clk); px <= 11'd700; py <= 10'd400;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_r !== 8'h10 || out_g !== 8'h20 || out_b !== 8'h30) begin
            $display("FAIL: Invalid joint 3 not hidden! got %h %h %h", out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end

        // 6e. Midpoint of invalid edge {3,2} at (600,350) -> hidden (background)
        @(posedge pixel_clk); px <= 11'd600; py <= 10'd350;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_r !== 8'h10 || out_g !== 8'h20 || out_b !== 8'h30) begin
            $display("FAIL: Invalid edge {3,2} drawn! got %h %h %h", out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end else $display("PASS: Invalid joint & edge suppression OK");

        // 7. Posture OSD tag test: DOG-SIT (pose=2, label=2, valid=1 -> 0x15)
        axi_write(8'h18, 32'h0000_0015);
        axi_read(8'h18, rval);
        if (rval !== 32'h0000_0015) begin
            $display("FAIL: BOX_ATTR pose readback=%h", rval); err_cnt = err_cnt + 1;
        end
        axi_write(8'h04, 32'h4); // OSD_COMMIT
        repeat (10) @(posedge pixel_clk);
        @(posedge pixel_clk); vs_frame_start <= 1'b1;
        @(posedge pixel_clk); vs_frame_start <= 1'b0;
        // Char 4 ('S') bg at rel_x=64 (px=164, py=82) -> yellow (0xFF, 0xFF, 0x00)
        @(posedge pixel_clk); de <= 1'b1; px <= 11'd164; py <= 10'd82;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_r !== 8'hFF || out_g !== 8'hFF || out_b !== 8'h00) begin
            $display("FAIL: DOG-SIT tag bg expected yellow, got %h %h %h", out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end
        // Char 4 ('S') fg at rel_x=68 (px=168, py=82) -> black text (0x00, 0x00, 0x00)
        @(posedge pixel_clk); de <= 1'b1; px <= 11'd168; py <= 10'd82;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_r !== 8'h00 || out_g !== 8'h00 || out_b !== 8'h00) begin
            $display("FAIL: DOG-SIT char S fg expected black, got %h %h %h", out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end
        // Char 6 ('T') fg at rel_x=102 (px=202, py=82) -> black text (0x00, 0x00, 0x00)
        @(posedge pixel_clk); de <= 1'b1; px <= 11'd202; py <= 10'd82;
        @(posedge pixel_clk);
        @(posedge pixel_clk); #1;
        if (out_r !== 8'h00 || out_g !== 8'h00 || out_b !== 8'h00) begin
            $display("FAIL: DOG-SIT char T fg expected black, got %h %h %h", out_r, out_g, out_b);
            err_cnt = err_cnt + 1;
        end else $display("PASS: DOG-SIT 7-char posture OSD tag OK");

        if (err_cnt == 0) $display("ALL_TB_PASS");
        else $display("TB_FAIL errors=%d", err_cnt);
        $finish;
    end
endmodule
