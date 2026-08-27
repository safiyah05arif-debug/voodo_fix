from pathlib import Path

citizen = Path(r"c:\Users\Safiya\OneDrive\Desktop\voodo_fix\templates\citizen.html")
text = citizen.read_text(encoding="utf-8")
en_old = "speechPrompt: 'Welcome to Nagara Setu. Point your camera at the civic issue, capture a photo, and confirm your live location.' }"
en_new = (
    "speechPrompt: 'Welcome to Nagara Setu. Point your camera at the civic issue, capture a photo, and confirm your live location.', "
    "easyRead: 'Easy Read', civicStanding: 'Your Civic Standing', reportsConfirmed: 'Reports confirmed', "
    "issuesResolved: 'Issues resolved', genuineUpvoted: 'Genuine issues upvoted', locationLbl: 'Location', "
    "reportedLbl: 'Reported', statusLbl: 'Status', resolvedLbl: 'Resolved', notYet: 'Not yet', yesLbl: 'Yes', "
    "completionProof: 'Completion proof' }"
)
ta_old = "speechPrompt: '\u0ba8\u0b95\u0bb0\u0baa\u0bcd \u0baa\u0bbf\u0bb0\u0b9a\u0bcd\u0b9a\u0bbf\u0ba9\u0bc8\u0baf\u0bc8 \u0ba8\u0bcb\u0b95\u0bcd\u0b95\u0bbf \u0b95\u0bc7\u0bae\u0bb0\u0bbe\u0bb5\u0bc8\u0ba4\u0bcd \u0ba4\u0bbf\u0bb0\u0bc1\u0baa\u0bcd\u0baa\u0bbf \u0baa\u0bc1\u0b95\u0bc8\u0baa\u0bcd\u0baa\u0b9f\u0bae\u0bcd \u0b8e\u0b9f\u0bc1\u0b95\u0bcd\u0b95\u0bb5\u0bc1\u0bae\u0bcd.' }"
if en_old not in text:
    raise SystemExit("en speechPrompt missing")
if ta_old not in text:
    # try to find actual ta speechPrompt
    idx = text.find("speechPrompt:", text.find("ta: {"))
    raise SystemExit("ta speechPrompt missing near: " + text[idx:idx+180])
citizen.write_text(text.replace(en_old, en_new, 1).replace(ta_old, ta_old[:-2] + ", easyRead: '\u0b8e\u0bb3\u0bbf\u0baf \u0bb5\u0bbe\u0b9a\u0bbf\u0baa\u0bcd\u0baa\u0bc1', civicStanding: '\u0b89\u0b99\u0bcd\u0b95\u0bb3\u0bcd \u0b95\u0bc1\u0b9f\u0bbf\u0bae\u0bc8 \u0ba8\u0bbf\u0bb2\u0bc8', reportsConfirmed: '\u0b89\u0bb1\u0bc1\u0ba4\u0bbf\u0baa\u0bcd\u0baa\u0b9f\u0bc1\u0ba4\u0bcd\u0ba4\u0baa\u0bcd\u0baa\u0b9f\u0bcd\u0b9f \u0baa\u0bc1\u0b95\u0bbe\u0bb0\u0bcd\u0b95\u0bb3\u0bcd', issuesResolved: '\u0ba4\u0bc0\u0bb0\u0bcd\u0b95\u0bcd\u0b95\u0baa\u0bcd\u0baa\u0b9f\u0bcd\u0b9f \u0baa\u0bbf\u0bb0\u0b9a\u0bcd\u0b9a\u0bbf\u0ba9\u0bc8\u0b95\u0bb3\u0bcd', genuineUpvoted: '\u0b86\u0ba4\u0bb0\u0bbf\u0b95\u0bcd\u0b95\u0baa\u0bcd\u0baa\u0b9f\u0bcd\u0b9f \u0b89\u0ba3\u0bcd\u0bae\u0bc8\u0baf\u0bbe\u0ba9 \u0baa\u0bc1\u0b95\u0bbe\u0bb0\u0bcd\u0b95\u0bb3\u0bcd', locationLbl: '\u0b87\u0b9f\u0bae\u0bcd', reportedLbl: '\u0baa\u0bc1\u0b95\u0bbe\u0bb0\u0bcd \u0ba8\u0bbe\u0bb3\u0bcd', statusLbl: '\u0ba8\u0bbf\u0bb2\u0bc8', resolvedLbl: '\u0ba4\u0bc0\u0bb0\u0bcd\u0b95\u0bcd\u0b95\u0baa\u0bcd\u0baa\u0b9f\u0bcd\u0b9f\u0ba4\u0bc1', notYet: '\u0b87\u0ba9\u0bcd\u0ba9\u0bc1\u0bae\u0bcd \u0b87\u0bb2\u0bcd\u0bb2\u0bc8', yesLbl: '\u0b86\u0bae\u0bcd', completionProof: '\u0bae\u0bc1\u0b9f\u0bbf\u0baa\u0bcd\u0baa\u0bc1 \u0b9a\u0bbe\u0ba9\u0bcd\u0bb1\u0bc1' }", 1), encoding="utf-8")
print("citizen ok")
