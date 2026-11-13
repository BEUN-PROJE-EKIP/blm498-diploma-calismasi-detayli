cmake_minimum_required(VERSION 3.16)
project(yayim_damga CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Paket adlarındaki sayı Gazebo büyük sürümüdür (kurulu paket adı); sürüm kilidi setup/versions.env'dedir.
find_package(gz-sim8 REQUIRED)
find_package(gz-transport13 REQUIRED)
find_package(gz-msgs10 REQUIRED)
find_package(gz-plugin2 REQUIRED COMPONENTS register)

add_library(YayimDamga SHARED yayim_damga.cc)
target_link_libraries(YayimDamga PRIVATE
  gz-sim8::gz-sim8 gz-transport13::gz-transport13 gz-msgs10::gz-msgs10 gz-plugin2::register)

add_executable(saat_kontrol saat_kontrol.cc)
