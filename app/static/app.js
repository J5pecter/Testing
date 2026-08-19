const jobsElement = document.querySelector("#jobs");
const messageElement = document.querySelector("#form-message");
const template = document.querySelector("#job-template");

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "Request failed.");
  return payload;
}

function setMessage(message, isError = false) {
  messageElement.textContent = message;
  messageElement.className = isError ? "error" : "";
}

async function loadConnection() {
  const status = await request("/api/settings/status");
  const heading = document.querySelector("#google-heading");
  const detail = document.querySelector("#google-detail");
  const button = document.querySelector("#google-connect");
  if (!status.google.client_configured) {
    heading.textContent = "Add Google client credentials";
    detail.textContent = "Put client_secret.json in this project, then click Connect Google. See ACCESS.md for the exact Google Cloud setup.";
    button.classList.add("disabled");
    button.href = "#";
  } else if (status.google.connected) {
    heading.textContent = "Google Drive and YouTube connected";
    detail.textContent = "Your OAuth token is saved locally. New transfers can now create Drive files and upload to your selected YouTube channel.";
    button.textContent = "Reconnect";
  } else {
    heading.textContent = "Connect Drive and YouTube";
    detail.textContent = "Authorize once in Google. This app never needs your Google password.";
    button.textContent = "Connect Google";
  }
}

function renderVideo(video) {
  const url = video.youtube_video_id ? `https://www.youtube.com/watch?v=${video.youtube_video_id}` : "";
  const title = document.createElement("strong");
  title.textContent = video.title;
  const meta = document.createElement("span");
  meta.className = "muted";
  meta.textContent = ` — ${video.status}`;
  const row = document.createElement("li");
  row.append(title, meta);
  if (url) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = " Open in YouTube";
    row.append(link);
  }
  if (video.error) {
    const error = document.createElement("small");
    error.className = "error";
    error.textContent = video.error;
    row.append(document.createElement("br"), error);
  }
  return row;
}

async function showVideos(job, container) {
  if (!container.classList.contains("hidden")) {
    container.classList.add("hidden");
    container.replaceChildren();
    return;
  }
  container.textContent = "Loading video details…";
  container.classList.remove("hidden");
  try {
    const data = await request(`/api/jobs/${job.id}`);
    const list = document.createElement("ul");
    list.className = "videos";
    data.videos.forEach((video) => list.append(renderVideo(video)));
    container.replaceChildren(list);
  } catch (error) {
    container.textContent = error.message;
  }
}

function renderJobs(jobs) {
  jobsElement.replaceChildren();
  if (!jobs.length) {
    jobsElement.innerHTML = '<p class="muted">No jobs yet.</p>';
    return;
  }
  jobs.forEach((job) => {
    const fragment = template.content.cloneNode(true);
    const card = fragment.querySelector(".job");
    card.querySelector(".job-user").textContent = `@${job.username}`;
    card.querySelector(".job-date").textContent = new Date(job.created_at).toLocaleString();
    const badge = card.querySelector(".job-status");
    badge.textContent = job.status.replaceAll("_", " ");
    badge.classList.add(`status-${job.status}`);
    card.querySelector(".job-message").textContent = job.message || "Waiting to start…";
    card.querySelector(".job-error").textContent = job.error || "";
    const cancel = card.querySelector(".cancel");
    if (!["queued", "running"].includes(job.status)) cancel.remove();
    else cancel.addEventListener("click", async () => {
      try {
        await request(`/api/jobs/${job.id}/cancel`, { method: "POST" });
        await loadJobs();
      } catch (error) { window.alert(error.message); }
    });
    const videoList = card.querySelector(".video-list");
    card.querySelector(".details").addEventListener("click", () => showVideos(job, videoList));
    jobsElement.append(card);
  });
}

async function loadJobs() {
  try { renderJobs(await request("/api/jobs")); }
  catch (error) { jobsElement.innerHTML = `<p class="error">${error.message}</p>`; }
}

document.querySelector("#job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Starting…");
  const profileUrl = document.querySelector("#profile-url").value;
  const privacy = document.querySelector("#privacy").value;
  const maxVideos = Number(document.querySelector("#max-videos").value || 0);
  const rightsConfirmed = document.querySelector("#rights-confirmed").checked;
  try {
    const job = await request("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_url: profileUrl, privacy, max_videos: maxVideos, rights_confirmed: rightsConfirmed }),
    });
    setMessage(`Transfer started for @${job.username}.`);
    event.target.reset();
    await loadJobs();
  } catch (error) { setMessage(error.message, true); }
});

document.querySelector("#refresh").addEventListener("click", loadJobs);
Promise.all([loadConnection(), loadJobs()]).catch((error) => console.error(error));
setInterval(loadJobs, 4000);
