# disykonect
Mutual exclusivity between Yubikey and network. Display a popup when both a Yubikey is plugged in and a network connection is present.

**This is a (old) work in progress**. It partially worked, but now throws exceptions on startup.

# Details
Detection of Yubikey is done via the Linux udev device manager. Network connectivity is checked via NetworkManager events on DBus. The popup window is handled via the Tk GUI toolkit.
