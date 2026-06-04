# Custom Threads Plugin for Fusion 360

A Fusion 360 plugin that lets you create and manage custom thread definitions. These custom threads are saved to Fusion's thread library and persist across upgrades.

## Installation

1. **Locate Fusion 360 Add-ins folder:**
   - On Windows: `%APPDATA%\Autodesk\ApplicationPlugins`
   - Create the `ApplicationPlugins` folder if it doesn't exist

2. **Copy the plugin:**
   - Copy the entire `CustomThreadsPlugin.bundle` folder to the ApplicationPlugins directory

3. **Enable the add-in in Fusion 360:**
   - Open Fusion 360
   - In the Design workspace, go to Utilities → Add-ins and Scripts
   - Find "CustomThreadsPlugin" in the list
   - Click the switch to enable it
   - Click "Run on Startup" checkbox to auto-load (optional)

4. **Use the plugin:**
   - Once enabled, you'll see "CreateCustomThread" toolbar utility become available
   - Click the "M+" icon to add a new custom thread
   - Enter diameter and pitch and a descriptive name if desired.
   - Click OK to save
   - Click on the "M<penicl>" icon to review, edit, and delete any custom plugins. 

## How It Works

The plugin saves custom thread definitions as an XML file alongside the other thread definitions in:
```
%LOCALAPPDATA%\Autodesk\webdeploy\production\<version>\Fusion\Server\Fusion\Configuration\ThreadData
```

A single new file contains all of the defined custom thread designations, in this format:
```xml
<?xml version='1.0' encoding='utf-8'?>
<ThreadDesignation>
  <ThreadSize>
    <Designation>M10x1.5</Designation>
    <Diameter>10</Diameter>
    <Pitch>1.5</Pitch>
  </ThreadSize>
</ThreadDesignation>
```

Fusion 360 reads this file on startup and adds it to your thread library.

## Backup & Restore

To preserve custom threads across Fusion upgrades:

1. **Backup:** Copy the thread XML files from `%LOCALAPPDATA%\Autodesk\webdeploy\production\<version>\Fusion\Server\Fusion\Configuration\ThreadData` to a safe location
2. **Restore:** After upgrade, copy the backed-up XML files back to the same directory
3. Restart Fusion 360

Alternatively, keep the thread files in version control or cloud storage for easy distribution across machines.

If you have the ThreadKeeper AddIn, this plugin will automatically back up the file to that plugin's folder when the file is modified. 
