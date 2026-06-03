# Installation Guide

## Step 1: Locate the AddIns Folder

### Windows
1. Press `Win + R` to open Run dialog
2. Type: `%APPDATA%\Autodesk\Fusion 360 API\AddIns`
3. Press Enter
4. If the folder doesn't exist, create it:
   - Right-click in the parent folder (`Fusion 360 API`)
   - Select "New → Folder"
   - Name it `AddIns`

## Step 2: Copy the Plugin

1. Copy the **`CustomThreadsPlugin.bundle`** folder (the one ending in `.bundle`)
2. Paste it into the AddIns folder you found in Step 1

Your final folder structure should look like:
```
C:\Users\[YourUsername]\AppData\Roaming\Autodesk\Fusion 360 API\AddIns\
└── CustomThreadsPlugin.bundle\
    ├── PackageContents.xml
    └── Contents\
        ├── CustomThreadsPlugin.manifest
        └── CustomThreadsPlugin.py
```

## Step 3: Enable in Fusion 360

1. **Open Fusion 360**
2. Open the Scripts and Add-Ins dialog — the easiest way is the keyboard shortcut **`Shift + S`**
   - Alternatively: in the Design workspace, click the **Tools** tab in the ribbon toolbar, then click **Scripts and Add-Ins**
3. Click the **"Add-Ins"** tab at the top of the dialog
4. Look for **"Custom Metric Threads"** in the list
5. Click **Run** to load it once, or tick **Run on Startup** to load it automatically every time Fusion launches

## Step 4: Verify Installation

1. After clicking Run, the add-in dialog will open immediately
2. A dialog should appear with fields for Diameter and Pitch — this confirms it is working

## Using the Plugin

1. Press **`Shift + S`** → Add-Ins tab → select **Custom Metric Threads** → click **Run**
   *(If "Run on Startup" is enabled, the command will also appear in the Tools tab ribbon under Add-Ins)*
2. Fill in the dialog:
   - **Nominal Diameter (mm):** e.g., `10` for M10
   - **Pitch (mm):** e.g., `1.5`
   - The **Thread Info** box updates live with the designation, pitch diameter, minor diameter, and tap drill size
3. Click **OK** — you'll see a confirmation message with the file path
4. **Restart Fusion 360** to make the new thread appear in the Thread tool dropdown
5. In the Thread feature, select **"Custom Metric"** from the thread-type list to find your thread

## Using the Backup/Restore Script

The `backup_restore.py` script helps manage your threads:

### List your threads:
```cmd
python backup_restore.py list
```

### Backup all threads:
```cmd
python backup_restore.py backup
# Or specify a custom backup location:
python backup_restore.py backup --path "C:\backups\my_threads"
```

### Restore threads:
```cmd
python backup_restore.py restore "C:\backups\my_threads"
```

After restoring, restart Fusion 360 to load the threads.

## Troubleshooting

**Problem: Plugin doesn't appear in Add-ins list**
- Check the folder structure is correct
- Restart Fusion 360
- Verify manifest.xml has no syntax errors

**Problem: Custom threads don't show in thread list**
- Restart Fusion 360 after creating a thread
- Check that XML files were created in `%APPDATA%\Autodesk\Fusion 360 API\Fusion360\`

**Problem: Error dialog when clicking the command**
- Check that CustomThreads.py is in the same folder as manifest.xml
- Verify Python syntax is correct

**Problem: Need to uninstall**
- Delete the `CustomThreadsPlugin` folder from the AddIns directory
- Restart Fusion 360

## Notes

- Custom threads are stored separately from Fusion's default threads
- They're automatically backed up by the plugin
- Use the backup script before major Fusion updates
- Thread files use standard XML format and can be manually edited if needed
