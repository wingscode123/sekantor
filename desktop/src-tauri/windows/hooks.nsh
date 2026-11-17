; Included by Tauri's NSIS installer (tauri.conf.json bundle.windows.nsis.installerHooks).
; Errors are ignored throughout: an install or uninstall must not fail because the hub is down or the
; hooks were removed by hand. `stop --wait` returns only once the hub and its watchers have exited, so
; their files are no longer locked when NSIS replaces or deletes them.

!macro NSIS_HOOK_PREINSTALL
  ; Upgrade over a running hub: stop it before its files are overwritten.
  ${If} ${FileExists} "$INSTDIR\sekantor\sekantor.exe"
    nsExec::Exec '"$INSTDIR\sekantor\sekantor.exe" stop --wait'
    Pop $0
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec '"$INSTDIR\sekantor\sekantor.exe" stop --wait'
  Pop $0
  ; $UpdateMode is Tauri's (set from /UPDATE in un.onInit): an in-place update keeps what first run set
  ; up. A real uninstall removes SeKantor's Claude Code hooks and the login task.
  ${If} $UpdateMode <> 1
    nsExec::Exec '"$INSTDIR\sekantor\sekantor.exe" uninstall claude --global'
    Pop $0
    nsExec::Exec '"$INSTDIR\sekantor\sekantor.exe" service uninstall'
    Pop $0
  ${EndIf}
!macroend
