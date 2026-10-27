/* Bounded development UI sampler. No persistence or device writes. */
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc.h>
#include <sys/proc_internal.h>
#include <kern/task.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#if defined(ARM64_BOARD_CONFIG_MARBLE)
extern task_t proc_task(proc_t);
extern task_t marble_sample_task_reference(task_t);
extern void marble_sample_task(const char *, int, task_t);
extern void thread_terminate_self(void);
extern int hz;
void marble_ui_sample_start(void);
static int
marble_sample_proc(proc_t p, void *arg)
{
    char name[32] = {0};
    proc_name(proc_pid(p), name, sizeof(name));
    if (strcmp(name, "SpringBoard") && strcmp(name, "backboardd")) return PROC_RETURNED;
    task_t task = marble_sample_task_reference(proc_task(p));
    if (task != TASK_NULL) {
        (*(unsigned *)arg)++;
        marble_sample_task(name, proc_pid(p), task);
        task_deallocate(task);
    }
    return PROC_RETURNED;
}
static void
marble_sample_thread(__unused void *arg, __unused wait_result_t wr)
{
    static int chan;
    (void)tsleep(&chan, PZERO, "marblesmp", 90*hz);
    for (unsigned i = 0; i < 3; i++) {
        unsigned found = 0;
        printf("MARBLE SMP BEGIN %u\n", i+1);
        proc_iterate(PROC_ALLPROCLIST, marble_sample_proc, &found, NULL, NULL);
        printf("MARBLE SMP END %u processes=%u\n", i+1, found);
        if (i != 2) (void)tsleep(&chan, PZERO, "marblesmp", 60*hz);
    }
    thread_terminate_self();
}
void
marble_ui_sample_start(void)
{
    int enabled = 0;
    if (!PE_parse_boot_argn("marble_ui_sample", &enabled, sizeof(enabled)) || enabled != 1) return;
    thread_t thread;
    kern_return_t kr = kernel_thread_start(marble_sample_thread, NULL, &thread);
    if (kr == KERN_SUCCESS) thread_deallocate(thread);
    printf("MARBLE SMP start=%d schedule=90,150,210 seconds\n", kr);
}
#endif
