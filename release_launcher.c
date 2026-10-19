/* Native entry point for the portable, signed Python/Qt application. */
#include <mach-o/dyld.h>
#include <libgen.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) || !realpath(executable, resolved)) {
        perror("Locate app executable");
        return 1;
    }
    char *base = dirname(resolved);
    char python_home[PATH_MAX], python_path[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    const char *suffixes[] = {"/../Resources/python", "/../Resources/site-packages",
                             "/../Resources/python/bin/python3.15", "/../Resources/app.py"};
    char *paths[] = {python_home, python_path, python, script};
    for (int i = 0; i < 4; i++) {
        if (snprintf(paths[i], PATH_MAX, "%s%s", base, suffixes[i]) >= PATH_MAX) {
            fprintf(stderr, "App path too long\n");
            return 1;
        }
    }
    if (setenv("PYTHONHOME", python_home, 1) || setenv("PYTHONPATH", python_path, 1) ||
        setenv("PYTHONNOUSERSITE", "1", 1) || setenv("PYTHONDONTWRITEBYTECODE", "1", 1)) {
        perror("Set Python environment");
        return 1;
    }
    unsetenv("__PYVENV_LAUNCHER__");
    unsetenv("PYTHONEXECUTABLE");
    char **args = calloc((size_t)argc + 2, sizeof(char *));
    if (!args) return 1;
    args[0] = python;
    args[1] = script;
    for (int i = 1; i < argc; i++) args[i + 1] = argv[i];
    execv(python, args);
    perror("Launch embedded Python");
    free(args);
    return 1;
}
