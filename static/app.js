// Grab buttons and containers
const btn = document.getElementById('generateBtn');
const promptInput = document.getElementById('promptInput');
const flashcardContainer = document.querySelector('.card-container');
const flashcardContent = document.getElementById('flashcard-content');
const downloadBtn = document.getElementById('downloadBtn');
const downloadImageBtn = document.getElementById('downloadImageBtn');

btn.addEventListener('click', async () => {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    alert('Please enter a prompt.');
    return;
  }

  // UI feedback
  btn.disabled = true;
  btn.textContent = 'Generating…';

  try {
    // 1. Call backend
    const res = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    // 2. Convert Markdown → HTML
    const html = marked.parse(data.result);

    // 3. Inject into the 3D card’s front face
    flashcardContent.innerHTML = html;

    // 4. Reveal the card container
    flashcardContainer.classList.add('visible');
    console.log('downloadImageBtn is', downloadImageBtn);
    console.log('Showing download button…', downloadImageBtn);
    // downloadImageBtn.classList.remove('hidden');
    downloadImageBtn.style.display = 'inline-block';
    console.log('downloadImageBtn is', downloadImageBtn);
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    // Restore button
    btn.disabled = false;
    btn.textContent = 'Generate Flashcard';
  }
});


downloadImageBtn.addEventListener('click', () => {
  // 1. Pick only the front face element
  const frontFace = document.querySelector('.card__face--front');

  // 2. Use html2canvas on that element
  html2canvas(frontFace, {
    backgroundColor: null,
    scale: 2
  }).then(canvas => {
    canvas.toBlob(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'flashcard.png';
      a.click();
      URL.revokeObjectURL(url);
    });
  });
});

