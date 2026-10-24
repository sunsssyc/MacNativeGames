#pragma once
#import <Cocoa/Cocoa.h>
void totk_hint_install(NSWindow *window);
BOOL totk_hint_key(NSEvent *event, BOOL down);
int totk_hint_command(const char *line);   /* "hint ..." lines of the command channel, test sessions only (hint_test.inc) */
