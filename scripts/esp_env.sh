# Source this before idf.py: . scripts/esp_env.sh
# Install, outside the repository (docs/hardware_esp32.md, Building and flashing):
#   git clone --depth 1 -b v6.1 --recursive --shallow-submodules \
#       https://github.com/espressif/esp-idf.git ~/esp/esp-idf-v6.1
#   ~/esp/esp-idf-v6.1/install.sh esp32,esp32s3,esp32c3,esp32c6
export IDF_PATH="${IDF_PATH:-$HOME/esp/esp-idf-v6.1}"
. "$IDF_PATH/export.sh"
