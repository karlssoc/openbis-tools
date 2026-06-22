obtools — portable config folder
================================

The presence of this .obtools/ folder next to the obtools executable makes
obtools run in portable mode: the credentials file and the OpenBIS session
token are stored HERE (on the stick), not in the host PC's user profile.

First-time setup on the stick:

    Windows:   .\obtools.exe cred set
    macOS:     ./obtools cred set

That writes a passphrase-encrypted password into this folder. Keep the
passphrase in your head, not on the stick. Then test:

    obtools connect

Run `obtools cred show` to confirm this folder is the active config root.
