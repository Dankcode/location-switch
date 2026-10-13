Standalone Mac and Windows downloads with bundled Python and dependencies.

- **mac-arm64**: Apple Silicon Mac.
- **mac-intel**: Intel Mac.
- **windows-x64**: 64-bit Windows 10/11; install Apple Devices for USB drivers.

Extract the entire ZIP. On Mac open `start.command`; on Windows open
`LocationSwitch.exe`. The local control panel opens in your browser.
Keep the console open and restore real location before disconnecting.

Builds are unsigned and are checked for CLI, worker IPC, UI, and static assets
on each target OS. Windows physical iPhone testing is pending. Developer Mode
still requires Apple's on-device confirmations. First image setup needs internet.

See README.md for iOS 17.0–17.3.1 tunnel setup and troubleshooting.
