set script_dir [file dirname [file normalize [info script]]]
set proj_dir [file normalize [file join $script_dir ".."]]
set fpga_dir [file normalize [file join $proj_dir ".."]]
set cam_dir  [file join $fpga_dir "cam_yolo_ref"]
set ip_dir   [file join $fpga_dir "ip_base"]

create_project ac880_petlink_v2025 $proj_dir -part xc7z020clg484-2 -force

# Add RTL sources (read-only reference to cam_yolo submodules)
add_files -norecurse [list \
    "$proj_dir/rtl/ac880_petlink_top.v" \
    "$proj_dir/rtl/camera_hdmi_petlink_top.v" \
    "$proj_dir/rtl/petlink_ctrl_regs.v" \
    "$proj_dir/rtl/petlink_mailbox_capture.v" \
    "$proj_dir/rtl/petlink_osd.v" \
    "$cam_dir/rtl/camera_af/ov5640_af_camera.v" \
    "$cam_dir/rtl/camera_af/ov5640_af_ctrl.v" \
    "$cam_dir/rtl/camera_af/ov5640_af_rom.v" \
    "$cam_dir/rtl/camera_af/ov5640_init_bus_ctrl.v" \
    "$cam_dir/rtl/camera/axi_display_reader.v" \
    "$cam_dir/rtl/camera/axi_frame_writer.v" \
    "$cam_dir/rtl/camera/camera_ingress.v" \
    "$cam_dir/rtl/camera/sccb_master.v" \
    "$cam_dir/rtl/camera/stream_async_fifo.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/camera_clock_reset.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/ddr_clock_reset.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/ddr_controller.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/dvi_tx.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/frame_buffer_manager.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/ov5640_capture.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/imports/camera_init/ov5640_init_table_rgb.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/rgb565_packer.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/serializer_10to1.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/tmds_encode_rgb.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/tmds_encoder.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/video_clock_reset.v" \
    "$cam_dir/cam_yolo.srcs/sources_1/new/video_timing.v" \
]

import_ip -files [list \
    "$ip_dir/camera_clk/camera_clk.xci" \
    "$ip_dir/ddr_clk/ddr_clk.xci" \
    "$ip_dir/video_clk/video_clk.xci" \
    "$ip_dir/mig_7series_0/mig_7series_0.xci" \
]
upgrade_ip [get_ips]
file mkdir "$proj_dir/ac880_petlink_v2025.gen/sources_1/ip/mig_7series_0"
generate_target all [get_ips]

add_files -fileset constrs_1 -norecurse "$proj_dir/constraints/ac880_petlink_top.xdc"
update_compile_order -fileset sources_1

# Create Block Design ps7_sys
create_bd_design "ps7_sys"
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0

set_property -dict [list \
    CONFIG.PCW_PRESET_BANK0_VOLTAGE {LVCMOS 3.3V} \
    CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
    CONFIG.PCW_CRYSTAL_PERIPHERAL_FREQMHZ {33.333333} \
    CONFIG.PCW_UIPARAM_DDR_ENABLE {1} \
    CONFIG.PCW_UIPARAM_DDR_MEMORY_TYPE {DDR 3} \
    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125} \
    CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {32 Bit} \
    CONFIG.PCW_UIPARAM_DDR_FREQ_MHZ {533.333333} \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_DATA_EYE {1} \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_READ_GATE {1} \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_WRITE_LEVEL {1} \
    CONFIG.PCW_UIPARAM_DDR_BOARD_DELAY0 {0.25} \
    CONFIG.PCW_UIPARAM_DDR_BOARD_DELAY1 {0.25} \
    CONFIG.PCW_UIPARAM_DDR_BOARD_DELAY2 {0.25} \
    CONFIG.PCW_UIPARAM_DDR_BOARD_DELAY3 {0.25} \
    CONFIG.PCW_QSPI_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_QSPI_QSPI_IO {MIO 1 .. 6} \
    CONFIG.PCW_QSPI_GRP_SINGLE_SS_ENABLE {1} \
    CONFIG.PCW_SINGLE_QSPI_DATA_MODE {x4} \
    CONFIG.PCW_QSPI_PERIPHERAL_FREQMHZ {200} \
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} \
    CONFIG.PCW_ENET0_GRP_MDIO_ENABLE {1} \
    CONFIG.PCW_ENET0_GRP_MDIO_IO {MIO 52 .. 53} \
    CONFIG.PCW_ENET0_PERIPHERAL_FREQMHZ {1000 Mbps} \
    CONFIG.PCW_USB0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_USB0_USB0_IO {MIO 28 .. 39} \
    CONFIG.PCW_USB0_RESET_ENABLE {1} \
    CONFIG.PCW_USB0_RESET_IO {MIO 46} \
    CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
    CONFIG.PCW_UART1_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_UART1_UART1_IO {MIO 48 .. 49} \
    CONFIG.PCW_UART1_BAUD_RATE {115200} \
    CONFIG.PCW_I2C0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_I2C0_I2C0_IO {MIO 50 .. 51} \
    CONFIG.PCW_GPIO_MIO_GPIO_ENABLE {1} \
    CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
] [get_bd_cells processing_system7_0]

make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/DDR]
make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/FIXED_IO]
if {[llength [get_bd_intf_ports -quiet DDR_0]] > 0} { set_property name DDR [get_bd_intf_ports DDR_0] }
if {[llength [get_bd_intf_ports -quiet FIXED_IO_0]] > 0} { set_property name FIXED_IO [get_bd_intf_ports FIXED_IO_0] }

# 1. Control/OSD AXI4-Lite registers at 0x40000000 (4K)
create_bd_cell -type module -reference petlink_ctrl_regs petlink_ctrl_regs_0

# 2. 128KB True Dual Port BRAM Mailbox at 0x42000000 (holds 256x144x2 = 73728 B)
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl:4.1 axi_bram_ctrl_0
set_property -dict [list CONFIG.SINGLE_PORT_BRAM {1}] [get_bd_cells axi_bram_ctrl_0]
apply_bd_automation -rule xilinx.com:bd_rule:bram_cntlr -config {BRAM "Auto"} [get_bd_intf_pins axi_bram_ctrl_0/BRAM_PORTA]
set_property -dict [list CONFIG.Memory_Type {True_Dual_Port_RAM}] [get_bd_cells axi_bram_ctrl_0_bram]

apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config { \
    Clk_master {/processing_system7_0/FCLK_CLK0 (100 MHz)} \
    Clk_slave {Auto} \
    Clk_xbar {Auto} \
    Master {/processing_system7_0/M_AXI_GP0} \
    Slave {/axi_bram_ctrl_0/S_AXI} \
    ddr_seg {Auto} \
    intc_ip {New AXI SmartConnect} \
    master_apm {0} \
} [get_bd_intf_pins axi_bram_ctrl_0/S_AXI]

apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config { \
    Clk_master {/processing_system7_0/FCLK_CLK0 (100 MHz)} \
    Clk_slave {Auto} \
    Clk_xbar {Auto} \
    Master {/processing_system7_0/M_AXI_GP0} \
    Slave {/petlink_ctrl_regs_0/s_axi} \
    ddr_seg {Auto} \
    intc_ip {/axi_smc} \
    master_apm {0} \
} [get_bd_intf_pins petlink_ctrl_regs_0/s_axi]

assign_bd_address -target_address_space /processing_system7_0/Data [get_bd_addr_segs axi_bram_ctrl_0/S_AXI/Mem0] -force
set_property offset 0x42000000 [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_bram_ctrl_0_Mem0}]
set_property range 128K [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_bram_ctrl_0_Mem0}]

assign_bd_address -target_address_space /processing_system7_0/Data [get_bd_addr_segs petlink_ctrl_regs_0/s_axi/reg0] -force
set_property offset 0x40000000 [get_bd_addr_segs {processing_system7_0/Data/SEG_petlink_ctrl_regs_0_reg0}]
set_property range 4K [get_bd_addr_segs {processing_system7_0/Data/SEG_petlink_ctrl_regs_0_reg0}]

# Export BRAM_PORTB and control/box signals to ac880_petlink_top
make_bd_intf_pins_external [get_bd_intf_pins axi_bram_ctrl_0_bram/BRAM_PORTB]
if {[llength [get_bd_intf_ports -quiet BRAM_PORTB_0]] > 0} { set_property name BRAM_PORTB [get_bd_intf_ports BRAM_PORTB_0] }

create_bd_port -dir O -type clk axi_clk
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_ports axi_clk]

create_bd_port -dir O -type rst axi_resetn
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_ports axi_resetn]

foreach pname {cmd_req cmd_release box_x1 box_y1 box_x2 box_y2 box_valid box_label box_pose box_commit_toggle kpt_x_flat kpt_y_flat kpt_valid} {
    make_bd_pins_external [get_bd_pins petlink_ctrl_regs_0/$pname]
    if {[llength [get_bd_ports -quiet ${pname}_0]] > 0} { set_property name $pname [get_bd_ports ${pname}_0] }
}
foreach pname {status_busy status_ready frame_seq last_pix_cnt} {
    make_bd_pins_external [get_bd_pins petlink_ctrl_regs_0/$pname]
    if {[llength [get_bd_ports -quiet ${pname}_0]] > 0} { set_property name $pname [get_bd_ports ${pname}_0] }
}

validate_bd_design
save_bd_design
generate_target all [get_files "$proj_dir/ac880_petlink_v2025.srcs/sources_1/bd/ps7_sys/ps7_sys.bd"]

set_property top ac880_petlink_top [current_fileset]
update_compile_order -fileset sources_1

launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "Synthesis failed!"
}

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "Implementation or bitstream failed!"
}

open_run impl_1
report_timing_summary -file "$proj_dir/timing_full.rpt" -quiet
report_utilization -file "$proj_dir/utilization_full.rpt" -quiet
write_hw_platform -fixed -include_bit -force -file "$proj_dir/ac880_petlink_full.xsa"
file copy -force "$proj_dir/ac880_petlink_v2025.runs/impl_1/ac880_petlink_top.bit" "$proj_dir/ac880_petlink_full.bit"

puts "BUILD_FULL_SUCCESS"
