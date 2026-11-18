const repository = 'https://github.com/DenysIvko/agent-sessions';
fetch('https://api.github.com/repos/DenysIvko/agent-sessions/releases/latest')
  .then(response => { if (!response.ok) throw new Error('No published release'); return response.json(); })
  .then(release => {
    if (release.draft || release.prerelease || !/^v\d+\.\d+\.\d+$/.test(release.tag_name)) return;
    let downloads = 0;
    for (const button of document.querySelectorAll('[data-asset]')) {
      const name = button.dataset.asset;
      const url = `${repository}/releases/download/${release.tag_name}/${name}`;
      if (release.assets.some(asset => asset.name === name && asset.browser_download_url === url)) {
        button.href = url;
        downloads++;
      }
    }
    if (downloads) {
      document.querySelector('#release-status').textContent = `${release.tag_name} is available.`;
      document.querySelector('#release-detail').textContent = 'Installers and checksums are hosted on GitHub Releases.';
    }
  })
  .catch(() => {});
