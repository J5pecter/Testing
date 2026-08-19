# Access and one-time setup

This application does **not** request an Instagram password, an Instagram cookie, or a Meta token. It is intentionally limited to public Instagram profile URLs. The profile must be public and the videos must be yours (or licensed for your YouTube channel).

## Required access

| System | What you provide | Why it is needed |
| --- | --- | --- |
| Instagram | A public profile URL only | The public downloader reads video posts visible without signing in. |
| Google account | One browser-based OAuth approval | Lets the application use the Drive and YouTube channel belonging to the Google account you select. No password is shared with the app. |
| Google Drive API | `drive.file` OAuth scope | Create a job folder, upload the downloaded files, then delete only the files that this app created after the YouTube upload succeeds. |
| YouTube Data API v3 | `youtube.upload` OAuth scope | Upload videos and metadata to the selected YouTube channel. |

The app stores its Google refresh token locally in `data/google_token.json`. Treat that file like a password: do not email it, commit it, or put it in a shared folder. Revoke access from your Google account's third-party access page if needed.

## Google Cloud configuration

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project.
2. In **APIs & Services → Library**, enable **Google Drive API** and **YouTube Data API v3**.
3. Configure the **OAuth consent screen**. For personal use, choose External and add your Google account as a Test User while the project is in testing.
4. In **Credentials**, create an **OAuth client ID** of type **Web application**.
5. Add this Authorized redirect URI exactly (use the host and port from `APP_BASE_URL`):

   ```text
   http://127.0.0.1:8000/api/auth/google/callback
   ```

   Add `http://localhost:8000/api/auth/google/callback` too if you set `APP_BASE_URL` to localhost.
6. Download the client JSON and save it as `client_secret.json` in this project folder. It is ignored by Git.
7. Start the app and select **Connect Google**. In the browser, choose the Google account that owns the target Drive and YouTube channel, then approve Drive-file and YouTube-upload permissions.

Use the same Google account for Drive and the desired YouTube channel. If the account manages multiple channels/brand accounts, Google/YouTube will associate uploads with the currently selected channel.

For the production deployment, use a **Web application** OAuth client and add the hosted callback URL exactly as `https://your-domain/api/auth/google/callback`. The host, scheme, path, and trailing slash must exactly match the redirect URI set in Google Cloud.

## Important operational limits

- A public Instagram profile can still rate-limit or block anonymous automated requests. This app does not bypass such restrictions. Wait and retry later if that happens.
- The default YouTube Data API quota is typically 10,000 units/day; a video upload costs roughly 1,600 units. Plan for about six uploads/day unless Google grants more quota.
- The default upload visibility is **private**. Check title, description, and copyright status in YouTube Studio before changing a video to public.
- Google Drive files are deleted only after the YouTube API reports a successful upload ID. If the YouTube upload fails, the Drive copy is retained.
- Instagram and YouTube rules, copyright, music licenses, and creator permissions still apply. Do not use the tool to copy content you do not own or control.
