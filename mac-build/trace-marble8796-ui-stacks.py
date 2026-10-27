"""Opt-in, bounded UI task stack sampling; dry-run unless --apply.

Acquire a task reference from the active task list under its lifetime lock.
Acquire thread references under task lock, then release that lock before
thread_get_state, remote map reads or console output. Samples are advisory:
threads resume after register capture and their stacks may change.
"""
from pathlib import Path
from datetime import datetime
import argparse

TASK = r'''
#if defined(ARM64_BOARD_CONFIG_MARBLE)
/* MARBLE_UI_SAMPLE_TASK_REF: candidate is compared, never dereferenced. */
task_t marble_sample_task_reference(task_t candidate);
task_t
marble_sample_task_reference(task_t candidate)
{
    task_t item, result = TASK_NULL;
    lck_mtx_lock(&tasks_threads_lock);
    queue_iterate(&tasks, item, task_t, tasks) {
        if (item == candidate) {
            task_reference(item);
            result = item;
            break;
        }
    }
    lck_mtx_unlock(&tasks_threads_lock);
    return result;
}
#endif
'''

SAMPLE = r'''
/* MARBLE_UI_SAMPLE_STACKS: 6 threads, 12 frames; no locks over reads/printf. */
#include <mach/arm/thread_status.h>
extern kern_return_t thread_get_state(thread_t, int, thread_state_t, mach_msg_type_number_t *);
void marble_sample_task(const char *name, int pid, task_t task);
void
marble_sample_task(const char *name, int pid, task_t task)
{
    thread_t refs[6], thread;
    unsigned count = 0;
    uint64_t mh = 0, slide = 0;
    vm_map_t map = get_task_map_reference(task);
    if (map == VM_MAP_NULL) {
        printf("MARBLE SMP %s[%d] inactive\n", name, pid);
        return;
    }
    vm_shared_region_t sr = vm_shared_region_get(task);
    if (sr != NULL) {
        slide = sr->sr_slide;
        vm_shared_region_deallocate(sr);
    }
    task_lock(task);
    if (task->active) {
        mh = task->mach_header_vm_address;
        queue_iterate(&task->threads, thread, thread_t, task_threads) {
            if (count == 6) break;
            thread_reference(thread);
            refs[count++] = thread;
        }
    }
    task_unlock(task);
    printf("MARBLE SMP %s[%d] slide=0x%llx mh=0x%llx threads=%u\n", name, pid, slide, mh, count);
    for (unsigned i = 0; i < count; i++) {
        arm_thread_state64_t state = {0};
        mach_msg_type_number_t words = ARM_THREAD_STATE64_COUNT;
        kern_return_t kr = thread_get_state(refs[i], ARM_THREAD_STATE64,
            (thread_state_t)&state, &words);
        thread_deallocate(refs[i]);
        if (kr != KERN_SUCCESS || words != ARM_THREAD_STATE64_COUNT) {
            printf("MARBLE SMP %s t%u state_error=%d\n", name, i, kr);
            continue;
        }
        char line[400];
        int n = snprintf(line, sizeof(line), "MARBLE SMP %s t%u pc=0x%llx lr=0x%llx sp=0x%llx bt",
            name, i, state.pc, state.lr, state.sp);
        uint64_t fp = state.fp;
        for (unsigned j = 0; j < 12 && fp && !(fp & 7) && n < (int)sizeof(line)-21; j++) {
            uint64_t frame[2];
            if (fp > UINT64_MAX - sizeof(frame) ||
                vm_map_read_user(map, fp, frame, sizeof(frame)) != KERN_SUCCESS) break;
            n += snprintf(line+n, sizeof(line)-n, " 0x%llx", frame[1]);
            if (frame[0] <= fp || frame[0]-fp > 1024*1024) break;
            fp = frame[0];
        }
        printf("%s\n", line);
    }
    vm_map_deallocate(map);
}
'''

BSD = r'''/* Bounded development UI sampler. No persistence or device writes. */
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
'''

def once(text, old, new):
    assert text.count(old)==1, ('anchor',old[:80],text.count(old))
    return text.replace(old,new,1)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,default=Path.home()/'unixnu-marble8796-build/xnu')
    p.add_argument('--apply',action='store_true')
    a=p.parse_args();r=a.source_root
    paths=['osfmk/kern/task.c','osfmk/kern/exception.c','bsd/kern/bsd_init.c','bsd/conf/files']
    old={s:(r/s).read_text() for s in paths}
    assert 'MARBLE_UI_SAMPLE_TASK_REF' not in old[paths[0]]
    assert not (r/'bsd/dev/marble_ui_sample.c').exists()
    new=dict(old)
    new[paths[0]]+=TASK
    new[paths[1]]=once(new[paths[1]],'#endif /* ARM64_BOARD_CONFIG_MARBLE */',SAMPLE+'\n#endif /* ARM64_BOARD_CONFIG_MARBLE */')
    new[paths[2]]=once(new[paths[2]],'\tload_init_program(p);','''#if defined(ARM64_BOARD_CONFIG_MARBLE)
    extern void marble_ui_sample_start(void);
    marble_ui_sample_start();
#endif
\tload_init_program(p);''')
    new[paths[3]]+='\nbsd/dev/marble_ui_sample.c\t\tstandard\n'
    print('Validated anchors: opt-in 3 rounds, 2 process names, 6 threads, 12 frames')
    if not a.apply: return
    backup=r/'trace-backups'/datetime.now().strftime('%Y%m%d-ui-sampler-%H%M%S');backup.mkdir(parents=True,exist_ok=False)
    for s,v in old.items():
        target=backup/s;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(v)
    for s,v in new.items(): (r/s).write_text(v)
    (r/'bsd/dev/marble_ui_sample.c').write_text(BSD)
    print('Applied; backup:',backup)

if __name__=='__main__': main()
