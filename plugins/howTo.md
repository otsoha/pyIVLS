## How to add plugins:
1. Copy the template
2. Implement necessary hooks, update imports etc. 
3. Fill in the provided .ini template
4. In the GUI, open the pluginloader subwindow
4. import plugin, the loader handles basic checks and updates the global config.
The name given in the ini file should match the file pyIVLS_{name}.py and the object inside pyIVLS_{name}_plugin. Otherwise naming is not important.
The address (dir) of the plugin is read on import, so the dir can have any name. The .ini file is also loaded while importing, so the name does not matter.

## How to remove plugins:
Currently removing plugins is only available by removing them from pyIVLS.ini

# What methods should a plugin have, the necessary interface:
- parse_settings_widget. SeqBuilder assumes this and uses it to check settings for plugins. 
- Seqbuilder also assumes "setSettings" to set current state for plugins
-"getIterations" 
-TODO: complete this section. 

# On writing hooks
-All args have to be named when the hook is called
for instance:
pm.hook.mm_move(1,0,0,0) crashes
pm.hook.mm_move(speed=1, x=0, y=0, z=0) works


# ini file:
Write dependencies with no spaces and comma separated values.


