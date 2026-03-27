Name "Titan VMOS Pro Standalone"
OutFile "titan-vmospro-standalone-setup.exe"
InstallDir "$PROGRAMFILES\TitanVMOSProStandalone"
RequestExecutionLevel admin

Page directory
Page instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "..\..\dist\windows\*"
  CreateShortCut "$DESKTOP\Titan VMOS Pro Standalone.lnk" "$INSTDIR\titan-vmospro-standalone.exe"
SectionEnd
