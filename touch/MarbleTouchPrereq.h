/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef MARBLE_TOUCH_PREREQ_H
#define MARBLE_TOUCH_PREREQ_H

#ifdef __cplusplus
extern "C" {
#endif

/* Read-only, boot-arg-gated caller entry; returns a bitmask of snapshot errors. */
int marble_touch_prereq_snapshot(void);

#ifdef __cplusplus
}
#endif

#endif
