cmake_minimum_required(VERSION 3.8)
project(swarm_msgs)

find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/VehicleState.msg"
  "msg/Mission.msg"
  "msg/ScanStart.msg"
  "msg/ScanFinished.msg"
  "msg/Complete.msg"
  "msg/Detection.msg"
  "msg/FrameResult.msg"
  "msg/Command.msg"
  DEPENDENCIES builtin_interfaces geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
