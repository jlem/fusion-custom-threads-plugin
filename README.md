# Custom Threads Plugin for Fusion 360

A Fusion 360 plugin that lets you create and manage custom thread definitions. These custom threads are saved to Fusion's thread library and persist across upgrades.

## Installation

1. **Locate Fusion 360 Add-ins folder:**
   - On Windows: `%APPDATA%\Autodesk\Fusion 360 API\AddIns`
   - Create the folder if it doesn't exist

2. **Copy the plugin:**
   - Copy the entire `CustomThreadsPlugin` folder to the AddIns directory

3. **Enable the add-in in Fusion 360:**
   - Open Fusion 360
   - Go to Tools → Add-ins and Scripts
   - Find "Custom Threads" in the list
   - Click the checkbox to enable it
   - Click "Run on Startup" to auto-load (optional)

4. **Use the plugin:**
   - Once enabled, you'll see "Create Custom Thread" command available
   - Click it to open the thread definition dialog
   - Enter thread name, diameter, and pitch
   - Click OK to save

## How It Works

The plugin saves custom thread definitions as XML files in:
```
%APPDATA%\Autodesk\Fusion 360 API\Fusion360\
```

Each custom thread is a separate XML file with this format:
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

Fusion 360 reads these files on startup and adds them to your thread library.

## Backup & Restore

To preserve custom threads across Fusion upgrades:

1. **Backup:** Copy the thread XML files from `%APPDATA%\Autodesk\Fusion 360 API\Fusion360\` to a safe location
2. **Restore:** After upgrade, copy the backed-up XML files back to the same directory
3. Restart Fusion 360

Alternatively, keep the thread files in version control or cloud storage for easy distribution across machines.

## Thread Naming Convention

Use standard thread designation naming:
- Metric: `M10x1.5` (diameter x pitch)
- UNC/UNF: `#10-32` (size - TPI)
- Custom: Any descriptive name works

## Troubleshooting

- **Threads not appearing:** Restart Fusion 360 after creating new thread definitions
- **Check file location:** Verify XML files are in `%APPDATA%\Autodesk\Fusion 360 API\Fusion360\`
- **Validate XML:** Ensure XML files are properly formatted (use an XML validator if needed)
