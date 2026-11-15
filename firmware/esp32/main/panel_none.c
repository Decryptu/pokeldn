/* panel_none.c: panel interface for boards with no screen wiring. */
#include "panel.h"

bool panel_init(void) { return false; }
void panel_present(const uint8_t *frame) { (void)frame; }
bool panel_power(uint8_t power) { (void)power; return false; }
