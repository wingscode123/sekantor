; Included by Tauri's NSIS installer (tauri.conf.json bundle.windows.nsis.installerHooks).
; Before the files go, remove what first run set up: SeKantor's hooks in ~/.claude/settings.json and the
; login task. A running hub is stopped first so its files can be deleted. Errors are ignored: an
; uninstall must not fail because the hub is down or the hooks were removed by hand.
!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec '"$INSTDIR\sekantor\sekantor.exe" stop'
  Pop $0
  nsExec::Exec '"$INSTDIR\sekantor\sekantor.exe" uninstall claude --global'
  Pop $0
  nsExec::Exec '"$INSTDIR\sekantor\sekantor.exe" service uninstall'
  Pop $0
!macroend
