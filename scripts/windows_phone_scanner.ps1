# ═══════════════════════════════════════════════════════════════════
#  TITAN — Windows Phone Scanner (No ADB Required)
#  Scans your Android phone through USB/MTP — READ ONLY
# ═══════════════════════════════════════════════════════════════════
#
#  HOW TO USE:
#  1. Connect your Android phone to Windows PC via USB
#  2. Select "File Transfer / MTP" on the phone (not charging only)
#  3. Open PowerShell as Administrator
#  4. Run: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#  5. Run: .\windows_phone_scanner.ps1
#  6. Results saved to: C:\TitanScan\
#
#  This script reads ONLY — makes ZERO changes to your phone.
# ═══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Continue"
$ScanDir = "C:\TitanScan"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ReportFile = "$ScanDir\phone_scan_$Timestamp.json"

# Create output directory
if (-not (Test-Path $ScanDir)) {
    New-Item -ItemType Directory -Path $ScanDir -Force | Out-Null
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  TITAN — Android Phone Scanner (No ADB)" -ForegroundColor Cyan
Write-Host "  Read-Only — Zero modifications" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$report = @{
    scan_timestamp  = (Get-Date -Format "o")
    scan_method     = "Windows MTP/USB — No ADB"
    sections        = @{}
}

# ─── 1. USB/PnP Device Detection ─────────────────────────────────

Write-Host "  [1/10] Detecting USB devices..." -ForegroundColor Yellow

$usbDevices = @()
try {
    $pnpDevices = Get-PnpDevice -Class "WPD" -Status "OK" -ErrorAction SilentlyContinue
    if (-not $pnpDevices) {
        $pnpDevices = Get-PnpDevice | Where-Object {
            $_.Class -in @("WPD", "USB", "AndroidUsbDeviceClass", "Portable Devices") -and
            $_.Status -eq "OK"
        }
    }
    
    foreach ($dev in $pnpDevices) {
        $usbDevices += @{
            name          = $dev.FriendlyName
            instance_id   = $dev.InstanceId
            manufacturer  = $dev.Manufacturer
            class         = $dev.Class
            status        = $dev.Status
            hardware_ids  = ($dev | Get-PnpDeviceProperty -KeyName "DEVPKEY_Device_HardwareIds" -ErrorAction SilentlyContinue).Data
        }
    }
} catch {
    Write-Host "    Could not query PnP devices: $($_.Exception.Message)" -ForegroundColor Red
}

# Also check USB controllers for Android VID/PID
$androidUsb = @()
try {
    $allUsb = Get-PnpDevice -Class "USB" -Status "OK" -ErrorAction SilentlyContinue
    foreach ($dev in $allUsb) {
        $hwIds = ($dev | Get-PnpDeviceProperty -KeyName "DEVPKEY_Device_HardwareIds" -ErrorAction SilentlyContinue).Data
        $hwIdStr = ($hwIds -join ",").ToLower()
        # Common Android USB Vendor IDs
        $androidVids = @("18d1", "04e8", "2717", "22b8", "0bb4", "1004", "2a70", "2ae5",
                         "05c6", "1bbb", "0fce", "0489", "2916", "1949", "2b4c", "29a9")
        $isAndroid = $false
        foreach ($vid in $androidVids) {
            if ($hwIdStr -match "vid_$vid") { $isAndroid = $true; break }
        }
        if ($isAndroid) {
            $androidUsb += @{
                name         = $dev.FriendlyName
                instance_id  = $dev.InstanceId
                manufacturer = $dev.Manufacturer
                hardware_ids = $hwIds
            }
        }
    }
} catch {}

$report.sections["usb_devices"] = @{
    wpd_devices    = $usbDevices
    android_usb    = $androidUsb
    device_count   = $usbDevices.Count + $androidUsb.Count
}

Write-Host "    Found $($usbDevices.Count) portable devices, $($androidUsb.Count) Android USB" -ForegroundColor Green

# ─── 2. Windows Device Manager Info ──────────────────────────────

Write-Host "  [2/10] Reading device identity from Windows..." -ForegroundColor Yellow

$deviceInfo = @{}
try {
    # Get detailed device properties for Android devices
    foreach ($dev in ($usbDevices + $androidUsb)) {
        $instId = $dev.instance_id
        if ($instId) {
            $pnp = Get-PnpDevice -InstanceId $instId -ErrorAction SilentlyContinue
            if ($pnp) {
                $props = @{}
                $propKeys = @(
                    "DEVPKEY_Device_FriendlyName",
                    "DEVPKEY_Device_Manufacturer",
                    "DEVPKEY_Device_Model",
                    "DEVPKEY_Device_BusReportedDeviceDesc",
                    "DEVPKEY_Device_DeviceDesc",
                    "DEVPKEY_Device_DriverVersion"
                )
                foreach ($key in $propKeys) {
                    try {
                        $val = ($pnp | Get-PnpDeviceProperty -KeyName $key -ErrorAction SilentlyContinue).Data
                        if ($val) { $props[$key] = $val }
                    } catch {}
                }
                $deviceInfo[$instId] = $props
            }
        }
    }
} catch {}

$report.sections["device_identity"] = $deviceInfo

# ─── 3. MTP Phone Storage Scan (via Shell.Application COM) ──────

Write-Host "  [3/10] Scanning phone storage via MTP..." -ForegroundColor Yellow

$mtpData = @{
    accessible   = $false
    phone_name   = ""
    storage_name = ""
    top_folders  = @()
    file_stats   = @{}
}

try {
    $shell = New-Object -ComObject Shell.Application
    
    # "This PC" / "Computer" namespace (17 = ssfDRIVES)
    $thisPC = $shell.NameSpace(17)
    
    $phoneFolder = $null
    $phoneName = ""
    
    foreach ($item in $thisPC.Items()) {
        $name = $item.Name
        $type = $item.Type
        # MTP devices show as "Portable Device" or phone model name
        if ($type -match "Portable|Phone|Device" -or
            $name -match "Galaxy|Samsung|iPhone|OnePlus|Pixel|Motorola|Xiaomi|Redmi|OPPO|Vivo|Huawei|Realme|Nokia|LG|Sony|Android|Phone") {
            $phoneFolder = $item.GetFolder()
            $phoneName = $name
            break
        }
    }
    
    if (-not $phoneFolder) {
        # Try all items — some phones show just model name without "Device" type
        foreach ($item in $thisPC.Items()) {
            $path = $item.Path
            if ($path -match "\\\\\\?\\") {
                # WPD path — likely an MTP device
                $phoneFolder = $item.GetFolder()
                $phoneName = $item.Name
                break
            }
        }
    }
    
    if ($phoneFolder) {
        $mtpData.accessible = $true
        $mtpData.phone_name = $phoneName
        Write-Host "    Phone found: $phoneName" -ForegroundColor Green
        
        # List storage volumes (Internal Storage, SD Card)
        foreach ($storage in $phoneFolder.Items()) {
            $storageName = $storage.Name
            $mtpData.storage_name = $storageName
            Write-Host "    Storage: $storageName" -ForegroundColor Green
            
            $storageFolder = $storage.GetFolder()
            if ($storageFolder) {
                # List top-level folders
                $topFolders = @()
                foreach ($folder in $storageFolder.Items()) {
                    $fname = $folder.Name
                    $fsize = $folder.Size
                    $ftype = $folder.Type
                    $fdate = $folder.ModifyDate
                    $topFolders += @{
                        name          = $fname
                        type          = $ftype
                        size_bytes    = $fsize
                        modified      = "$fdate"
                    }
                }
                $mtpData.top_folders = $topFolders
                
                # Scan key directories for file stats
                $scanDirs = @("DCIM", "Download", "Documents", "Pictures", "Music",
                              "WhatsApp", "Telegram", "Android", "Movies", "Recordings")
                
                foreach ($dirName in $scanDirs) {
                    foreach ($folder in $storageFolder.Items()) {
                        if ($folder.Name -eq $dirName) {
                            $dirInfo = @{ file_count = 0; subfolder_count = 0; sample_files = @() }
                            try {
                                $subFolder = $folder.GetFolder()
                                if ($subFolder) {
                                    $count = 0
                                    foreach ($f in $subFolder.Items()) {
                                        if ($f.IsFolder) {
                                            $dirInfo.subfolder_count++
                                        } else {
                                            $dirInfo.file_count++
                                            if ($count -lt 5) {
                                                $dirInfo.sample_files += @{
                                                    name     = $f.Name
                                                    size     = $f.Size
                                                    modified = "$($f.ModifyDate)"
                                                }
                                            }
                                        }
                                        $count++
                                        if ($count -gt 500) { break }  # limit scan depth
                                    }
                                }
                            } catch {}
                            $mtpData.file_stats[$dirName] = $dirInfo
                            break
                        }
                    }
                }
            }
        }
    } else {
        Write-Host "    No MTP phone detected in This PC" -ForegroundColor Red
        Write-Host "    Make sure: Phone is connected USB + MTP mode selected" -ForegroundColor Yellow
    }
} catch {
    Write-Host "    MTP scan error: $($_.Exception.Message)" -ForegroundColor Red
}

$report.sections["mtp_storage"] = $mtpData

# ─── 4. Device Manager: Detailed Hardware ────────────────────────

Write-Host "  [4/10] Reading hardware details from Device Manager..." -ForegroundColor Yellow

$hardwareDetails = @{}
try {
    # WMI queries for USB device info
    $wmiUsb = Get-WmiObject -Class Win32_PnPEntity -ErrorAction SilentlyContinue | Where-Object {
        $_.DeviceID -match "USB" -and $_.Name -match "Android|MTP|Phone|Galaxy|Pixel|OnePlus"
    } | Select-Object Name, DeviceID, Manufacturer, Description, Service, Status -First 10
    
    $hardwareDetails["wmi_usb"] = @($wmiUsb | ForEach-Object {
        @{
            name         = $_.Name
            device_id    = $_.DeviceID
            manufacturer = $_.Manufacturer
            description  = $_.Description
            service      = $_.Service
        }
    })
    
    # Portable device serial number from registry
    $regPortable = Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Enum\USB" -ErrorAction SilentlyContinue |
        Get-ChildItem -ErrorAction SilentlyContinue |
        Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).FriendlyName -match "Phone|Android|Galaxy|Pixel|MTP" }
    
    foreach ($item in $regPortable) {
        $serial = Split-Path $item.PSPath -Leaf
        $friendly = (Get-ItemProperty $item.PSPath -ErrorAction SilentlyContinue).FriendlyName
        $hardwareDetails["serial_from_registry"] = $serial
        $hardwareDetails["friendly_from_registry"] = $friendly
        break
    }
} catch {}

$report.sections["hardware_details"] = $hardwareDetails

# ─── 5. Network Interfaces (Windows PC side) ─────────────────────

Write-Host "  [5/10] Scanning Windows network (for USB tethering)..." -ForegroundColor Yellow

$networkInfo = @{}
try {
    $adapters = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        $_.Status -eq "Up" -or $_.InterfaceDescription -match "RNDIS|Android|Remote NDIS|USB Ethernet"
    }
    $networkInfo["adapters"] = @($adapters | ForEach-Object {
        @{
            name          = $_.Name
            description   = $_.InterfaceDescription
            status        = "$($_.Status)"
            mac           = $_.MacAddress
            link_speed    = $_.LinkSpeed
            media_type    = $_.MediaType
        }
    })
    
    # Check for RNDIS (USB tethering from phone)
    $rndis = $adapters | Where-Object { $_.InterfaceDescription -match "RNDIS|Android|Remote NDIS" }
    $networkInfo["usb_tethering_detected"] = ($null -ne $rndis)
    if ($rndis) {
        $rndisIp = Get-NetIPAddress -InterfaceIndex $rndis.ifIndex -ErrorAction SilentlyContinue
        $networkInfo["tethering_ip"] = @($rndisIp | ForEach-Object { $_.IPAddress })
    }
} catch {}

$report.sections["windows_network"] = $networkInfo

# ─── 6. Installed Android Drivers ─────────────────────────────────

Write-Host "  [6/10] Checking installed Android drivers..." -ForegroundColor Yellow

$driverInfo = @{}
try {
    $drivers = Get-WmiObject -Class Win32_PnPSignedDriver -ErrorAction SilentlyContinue | Where-Object {
        $_.DeviceName -match "Android|ADB|MTP|Samsung|Google|Qualcomm|MediaTek" -or
        $_.InfName -match "android|adb|wpdmtp|samsung|google"
    } | Select-Object DeviceName, DriverVersion, Manufacturer, InfName, IsSigned -First 20
    
    $driverInfo["drivers"] = @($drivers | ForEach-Object {
        @{
            device   = $_.DeviceName
            version  = $_.DriverVersion
            vendor   = $_.Manufacturer
            inf      = $_.InfName
            signed   = $_.IsSigned
        }
    })
    
    # Check if ADB interface is available (even if blocked) 
    $adbInterface = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object {
        $_.FriendlyName -match "ADB|Android Debug" -or
        $_.InstanceId -match "ADB"
    }
    $driverInfo["adb_interface_visible"] = ($null -ne $adbInterface)
    if ($adbInterface) {
        $driverInfo["adb_interface_status"] = "$($adbInterface.Status)"
        $driverInfo["adb_interface_name"] = $adbInterface.FriendlyName
    }
} catch {}

$report.sections["android_drivers"] = $driverInfo

# ─── 7. Windows Event Logs (USB connection events) ───────────────

Write-Host "  [7/10] Reading USB connection history..." -ForegroundColor Yellow

$eventInfo = @{}
try {
    # Recent USB device connect/disconnect events
    $usbEvents = Get-WinEvent -FilterHashtable @{
        LogName   = 'Microsoft-Windows-DriverFrameworks-UserMode/Operational'
        Level     = 4  # Information
    } -MaxEvents 50 -ErrorAction SilentlyContinue | Where-Object {
        $_.Message -match "MTP|USB|Android|Phone"
    } | Select-Object TimeCreated, Message -First 10
    
    $eventInfo["recent_connections"] = @($usbEvents | ForEach-Object {
        @{
            time    = "$($_.TimeCreated)"
            message = $_.Message.Substring(0, [Math]::Min(200, $_.Message.Length))
        }
    })
} catch {
    # Fallback: setupapi log
    try {
        $setupLog = Get-Content "C:\Windows\INF\setupapi.dev.log" -Tail 100 -ErrorAction SilentlyContinue |
            Select-String -Pattern "Android|MTP|Phone|Galaxy|Pixel|USB\\VID" |
            Select-Object -Last 10
        $eventInfo["setup_log_matches"] = @($setupLog | ForEach-Object { $_.Line.Trim() })
    } catch {}
}

$report.sections["usb_history"] = $eventInfo

# ─── 8. Check ADB Accessibility ──────────────────────────────────

Write-Host "  [8/10] Testing ADB accessibility..." -ForegroundColor Yellow

$adbCheck = @{
    adb_installed    = $false
    adb_path         = ""
    adb_can_see      = $false
    adb_authorized   = $false
    adb_blocked_reason = ""
}

# Find adb.exe
$adbPaths = @(
    "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    "C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe",
    "C:\Android\platform-tools\adb.exe",
    "$env:USERPROFILE\Downloads\platform-tools\adb.exe"
)

$adbExe = $null
foreach ($p in $adbPaths) {
    if (Test-Path $p) { $adbExe = $p; break }
}

# Also check PATH
if (-not $adbExe) {
    $adbExe = (Get-Command adb -ErrorAction SilentlyContinue).Source
}

if ($adbExe) {
    $adbCheck.adb_installed = $true
    $adbCheck.adb_path = $adbExe
    
    try {
        $adbOut = & $adbExe devices 2>&1 | Out-String
        $adbCheck.adb_raw_output = $adbOut.Trim()
        
        if ($adbOut -match "device$" -and $adbOut -notmatch "unauthorized") {
            $adbCheck.adb_can_see = $true
            $adbCheck.adb_authorized = $true
        } elseif ($adbOut -match "unauthorized") {
            $adbCheck.adb_can_see = $true
            $adbCheck.adb_authorized = $false
            $adbCheck.adb_blocked_reason = "ADB visible but unauthorized — check phone for auth prompt"
        } elseif ($adbOut -match "no permissions") {
            $adbCheck.adb_can_see = $true
            $adbCheck.adb_blocked_reason = "ADB visible but no permissions — driver issue"
        } else {
            $adbCheck.adb_blocked_reason = "No ADB device detected — USB Debugging likely disabled by carrier/MDM"
        }
    } catch {
        $adbCheck.adb_blocked_reason = "ADB command failed: $($_.Exception.Message)"
    }
} else {
    $adbCheck.adb_blocked_reason = "ADB not installed on Windows. Download: https://developer.android.com/tools/releases/platform-tools"
}

$report.sections["adb_status"] = $adbCheck

# ─── 9. Phone Model from USB Descriptors ─────────────────────────

Write-Host "  [9/10] Extracting phone model from USB descriptors..." -ForegroundColor Yellow

$usbDescriptors = @{}
try {
    # Parse USB VID:PID from registry
    $usbEnum = Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Enum\USB" -ErrorAction SilentlyContinue
    foreach ($vidpid in $usbEnum) {
        $name = Split-Path $vidpid.PSPath -Leaf
        if ($name -match "VID_(\w+)&PID_(\w+)") {
            $vid = $Matches[1]
            $pid = $Matches[2]
            
            # Known Android vendor IDs
            $androidVendors = @{
                "18D1" = "Google"; "04E8" = "Samsung"; "2717" = "Xiaomi";
                "22B8" = "Motorola"; "0BB4" = "HTC"; "1004" = "LG";
                "2A70" = "OnePlus"; "2AE5" = "Fairphone"; "05C6" = "Qualcomm";
                "1BBB" = "T-Mobile"; "0FCE" = "Sony"; "2916" = "Google/Nexus";
                "1949" = "Amazon"; "2B4C" = "Realme"; "29A9" = "Nothing";
                "12D1" = "Huawei"; "2D95" = "OPPO"; "2A45" = "Vivo"
            }
            
            if ($androidVendors.ContainsKey($vid.ToUpper())) {
                $serials = Get-ChildItem $vidpid.PSPath -ErrorAction SilentlyContinue
                foreach ($ser in $serials) {
                    $friendly = (Get-ItemProperty $ser.PSPath -ErrorAction SilentlyContinue).FriendlyName
                    $usbDescriptors["$vid`:$pid"] = @{
                        vendor      = $androidVendors[$vid.ToUpper()]
                        vid         = $vid
                        pid         = $pid
                        serial      = (Split-Path $ser.PSPath -Leaf)
                        friendly    = $friendly
                    }
                }
            }
        }
    }
} catch {}

$report.sections["usb_descriptors"] = $usbDescriptors

# ─── 10. Summary & Assessment ────────────────────────────────────

Write-Host "  [10/10] Generating assessment..." -ForegroundColor Yellow

$assessment = @{
    phone_detected       = ($mtpData.accessible -or $androidUsb.Count -gt 0 -or $usbDescriptors.Count -gt 0)
    phone_name           = $mtpData.phone_name
    mtp_accessible       = $mtpData.accessible
    adb_working          = $adbCheck.adb_authorized
    adb_blocked          = (-not $adbCheck.adb_authorized)
    carrier_lock_likely  = $false
    recommendations      = @()
}

# Determine if carrier-locked
if (-not $adbCheck.adb_authorized -and $assessment.phone_detected) {
    $assessment.carrier_lock_likely = $true
    $assessment.recommendations += "ADB is blocked — likely carrier/MDM restriction"
    $assessment.recommendations += "Try: Settings > Developer Options > Wireless Debugging (Android 11+)"
    $assessment.recommendations += "Try: Settings > Biometrics > Device Admin Apps > disable all admin apps"
}

if (-not $mtpData.accessible) {
    $assessment.recommendations += "Phone storage not accessible via MTP"
    $assessment.recommendations += "On phone: when USB connected, select 'File Transfer / MTP' (not 'Charging only')"
}

if (-not $adbCheck.adb_installed) {
    $assessment.recommendations += "Install ADB: Download platform-tools from developer.android.com"
}

# Storage analysis
$storageAssessment = @{}
if ($mtpData.file_stats.Count -gt 0) {
    foreach ($dir in $mtpData.file_stats.Keys) {
        $stats = $mtpData.file_stats[$dir]
        $storageAssessment[$dir] = @{
            files       = $stats.file_count
            subfolders  = $stats.subfolder_count
        }
    }
}
$assessment["storage_analysis"] = $storageAssessment

$report.sections["assessment"] = $assessment

# ─── Save Report ──────────────────────────────────────────────────

$jsonReport = $report | ConvertTo-Json -Depth 10
$jsonReport | Out-File -FilePath $ReportFile -Encoding UTF8

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  SCAN COMPLETE" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Print summary
Write-Host "  RESULTS:" -ForegroundColor White
Write-Host "  ─────────────────────────────────────────────────" -ForegroundColor DarkGray

if ($assessment.phone_detected) {
    Write-Host "  Phone Detected  : YES — $($mtpData.phone_name)" -ForegroundColor Green
} else {
    Write-Host "  Phone Detected  : NO" -ForegroundColor Red
}

Write-Host "  MTP Storage     : $(if($mtpData.accessible){'ACCESSIBLE'}else{'NOT ACCESSIBLE'})" -ForegroundColor $(if($mtpData.accessible){"Green"}else{"Red"})
Write-Host "  ADB Status      : $(if($adbCheck.adb_authorized){'WORKING'}elseif($adbCheck.adb_can_see){'VISIBLE BUT BLOCKED'}else{'BLOCKED'})" -ForegroundColor $(if($adbCheck.adb_authorized){"Green"}else{"Red"})

if ($adbCheck.adb_blocked_reason) {
    Write-Host "  ADB Block Reason: $($adbCheck.adb_blocked_reason)" -ForegroundColor Yellow
}

# USB descriptors
foreach ($key in $usbDescriptors.Keys) {
    $desc = $usbDescriptors[$key]
    Write-Host "  USB Device      : $($desc.vendor) [$key] Serial: $($desc.serial)" -ForegroundColor Cyan
}

# Top folders
if ($mtpData.top_folders.Count -gt 0) {
    Write-Host ""
    Write-Host "  PHONE STORAGE FOLDERS:" -ForegroundColor White
    foreach ($f in $mtpData.top_folders) {
        $sizeStr = if ($f.size_bytes -gt 1MB) { "$([math]::Round($f.size_bytes/1MB, 1)) MB" }
                   elseif ($f.size_bytes -gt 1KB) { "$([math]::Round($f.size_bytes/1KB, 1)) KB" }
                   else { "$($f.size_bytes) B" }
        Write-Host "    $($f.name)  ($sizeStr,  $($f.type))" -ForegroundColor Gray
    }
}

# File stats
if ($storageAssessment.Count -gt 0) {
    Write-Host ""
    Write-Host "  FILE COUNTS:" -ForegroundColor White
    foreach ($dir in $storageAssessment.Keys) {
        $s = $storageAssessment[$dir]
        Write-Host "    $dir : $($s.files) files, $($s.subfolders) subfolders" -ForegroundColor Gray
    }
}

# Drivers
if ($driverInfo.drivers.Count -gt 0) {
    Write-Host ""
    Write-Host "  ANDROID DRIVERS:" -ForegroundColor White
    foreach ($drv in $driverInfo.drivers) {
        Write-Host "    $($drv.device) [$($drv.vendor)] v$($drv.version) Signed=$($drv.signed)" -ForegroundColor Gray
    }
}

# ADB interface
if ($driverInfo.adb_interface_visible) {
    Write-Host "  ADB Interface   : $($driverInfo.adb_interface_name) ($($driverInfo.adb_interface_status))" -ForegroundColor Yellow
}

# Recommendations
if ($assessment.recommendations.Count -gt 0) {
    Write-Host ""
    Write-Host "  RECOMMENDATIONS:" -ForegroundColor Yellow
    foreach ($rec in $assessment.recommendations) {
        Write-Host "    > $rec" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  Report saved: $ReportFile" -ForegroundColor Green
Write-Host ""
Write-Host "  NEXT STEP: Copy C:\TitanScan\ to your RDP-shared drive" -ForegroundColor Cyan
Write-Host "  Or share C:\TitanScan as a network folder" -ForegroundColor Cyan
Write-Host ""

# Also copy to Desktop for easy access
$desktopCopy = "$env:USERPROFILE\Desktop\phone_scan_$Timestamp.json"
try {
    Copy-Item $ReportFile $desktopCopy -ErrorAction SilentlyContinue
    Write-Host "  Also copied to Desktop: $desktopCopy" -ForegroundColor Green
} catch {}
