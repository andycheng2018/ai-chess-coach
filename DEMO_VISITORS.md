# Visitor welcome

A short welcome opens on the first visit in a tab/app web session. It explains:
open easy capture practice, tap a piece and its destination, then keep exploring.
**Try an easy capture** opens the existing practice board without a Lichess login.
**Explore Chess Buddy** opens Home Hub. Closing the welcome returns to the page
that was already open. Dismissal is remembered in session storage across reloads.

For each next visitor, finish the previous live match, turn robot reactions off,
and choose **Next guest** in the shortcut row. This reopens the welcome and lets
the next person start a fresh practice view. It does not delete saved games,
analysis, chat history, account credentials or robot configuration. A browser
cannot identify a new physical visitor; the host uses this reset between people.
The button is blocked while robot reactions are armed/busy or a game is starting.

**Dog performance** opens the existing Dog stage flow. The host verifies the
space/handset Stop, previews the score, and starts through the existing fresh
readiness checks. Opening or dismissing instructions does not arm robot motion.
This is an explicit navigation action; automatic performance on welcome dismissal
has not been enabled while the intended click trigger is being clarified.

Validation: production build; first-session popup; dismissal persisting across
reload; Next guest reopening; practice navigation; performance navigation;
armed-controller reset blocking. Reset/navigation were tested in an isolated
frontend pointed at an unused backend port, so no physical show was started.
