// --- NEW MODULE IMPORTS ---
import * as pdfjsLib from '/static/pdfjs/pdf.mjs';
pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdfjs/pdf.worker.mjs';
// --- END NEW MODULE IMPORTS ---

document.addEventListener('DOMContentLoaded', () => {

    // --- Variables ---
    let pdfDoc = null;
    let currentPageNum = 1;
    let totalPages = 0;
    let currentLayerId = null;
    let currentHighlightedText = ""; 

    // --- DOM Elements ---
    const viewerContainer = document.getElementById('viewer-container');
    const viewerArea = document.getElementById('pdf-viewer-area');
    const prevPageBtn = document.getElementById('prev-page-btn');
    const nextPageBtn = document.getElementById('next-page-btn');
    const pageNumDisplay = document.getElementById('page-num-display');
    const pageCountDisplay = document.getElementById('page-count-display');

    const layerSelect = document.getElementById('layer-select');
    const annotationList = document.getElementById('annotation-list');
    const annotationTextarea = document.getElementById('annotation-textarea');
    const saveAnnotationBtn = document.getElementById('save-annotation-btn');
    
    // "New Journal" Button
    const addLayerBtn = document.getElementById('add-layer-btn');
    
    // Ask AI Button
    const askAiBtn = document.getElementById('ask-ai-btn');

    // --- Modal Elements (For Creating Layers) ---
    const createLayerModal = document.getElementById('createLayerModal');
    const newLayerNameInput = document.getElementById('newLayerName');
    const newLayerGroupSelect = document.getElementById('newLayerGroup');
    const cancelLayerBtn = document.getElementById('cancelLayerBtn');
    const confirmLayerBtn = document.getElementById('confirmLayerBtn');

    // --- SCROLL OBSERVER (Detects current page) ---
    const pageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                // Get page number from ID "page-wrapper-1"
                const pageId = entry.target.id;
                const pageNum = parseInt(pageId.split('-')[2]);
                if (pageNum) {
                    currentPageNum = pageNum;
                    pageNumDisplay.textContent = currentPageNum;
                }
            }
        });
    }, {
        root: viewerArea, // Watch scrolling inside this div
        threshold: 0.5    // Trigger when 50% of the page is visible
    });

    // --- PDF Loader ---
    async function loadPdf(pdfUrl) {
        console.log("Loading PDF from URL:", pdfUrl);
        try {
            const loadingTask = pdfjsLib.getDocument({
                url: pdfUrl,
                cMapUrl: 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.4.120/cmaps/',
                cMapPacked: true,
            });
            pdfDoc = await loadingTask.promise;
            totalPages = pdfDoc.numPages;
            pageCountDisplay.textContent = totalPages;
            await renderAllPages();
            setupTextSelection();
        } catch (error) {
            console.error('Error loading PDF:', error);
            alert('Could not load PDF file.');
        }
    }

    async function renderAllPages() {
        viewerContainer.innerHTML = '';
        const SCALE = 1.5;
        
        // Disconnect old observer if re-rendering
        pageObserver.disconnect();

        for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
            try {
                const page = await pdfDoc.getPage(pageNum);
                const viewport = page.getViewport({ scale: SCALE });

                const pageWrapper = document.createElement('div');
                pageWrapper.className = 'pdf-page-wrapper';
                
                // --- ADDED ID FOR OBSERVER ---
                pageWrapper.id = `page-wrapper-${pageNum}`;
                
                pageWrapper.style.width = `${viewport.width}px`;
                pageWrapper.style.height = `${viewport.height}px`;
                pageWrapper.style.position = 'relative'; 
                
                const canvas = document.createElement('canvas');
                canvas.className = 'pdf-page-canvas';
                canvas.height = viewport.height;
                canvas.width = viewport.width;
                
                pageWrapper.appendChild(canvas);
                viewerContainer.appendChild(pageWrapper);

                // Start observing this page for scroll tracking
                pageObserver.observe(pageWrapper);

                const renderContext = {
                    canvasContext: canvas.getContext('2d'),
                    viewport: viewport
                };
                await page.render(renderContext).promise;
                
                const textContent = await page.getTextContent();
                const textLayerDiv = document.createElement('div');
                textLayerDiv.className = 'textLayer';
                textLayerDiv.style.width = `${viewport.width}px`;
                textLayerDiv.style.height = `${viewport.height}px`;
                textLayerDiv.style.setProperty('--scale-factor', SCALE);

                pageWrapper.appendChild(textLayerDiv);
                
                await pdfjsLib.renderTextLayer({
                    textContentSource: textContent, 
                    container: textLayerDiv,
                    viewport: viewport,
                    textDivs: []
                }).promise;

            } catch (pageError) {
                console.error(`Error rendering page ${pageNum}:`, pageError);
            }
        }
    }
    
    function setupTextSelection() {
        viewerArea.addEventListener('mouseup', () => {
            const selection = window.getSelection();
            const selectedText = selection.toString().trim();
            
            if (selectedText.length > 0) {
                currentHighlightedText = selectedText;
            }
        });
    }

    // --- API Functions ---

    async function fetchLayers() {
        try {
            const response = await fetch(`/api/book/${EBOOK_ID}/layers`);
            const layers = await response.json();
            
            layerSelect.innerHTML = '<option value="" disabled selected>-- Select Journal / Group --</option>';
            if (layers.length === 0) layerSelect.innerHTML += '<option value="" disabled>No journals yet</option>';
            
            layers.forEach(layer => {
                const option = document.createElement('option');
                option.value = layer.id;
                option.textContent = layer.name + ` (by ${layer.creator_name})`;
                layerSelect.appendChild(option);
            });
        } catch (error) {
            console.error('Error fetching layers:', error);
        }
    }

    async function fetchAnnotations(layerId) {
        if (!layerId) {
            annotationList.innerHTML = '<p style="color: #6b7280; text-align: center; margin-top: 2rem;">Select a journal layer above.</p>';
            return;
        }
        currentLayerId = layerId;
        annotationList.innerHTML = '<p style="text-align:center; margin-top:2rem;">Loading...</p>';

        try {
            const response = await fetch(`/api/layer/${layerId}/annotations`);
            const annotations = await response.json();
            renderAnnotations(annotations);
        } catch (error) {
            console.error('Error:', error);
        }
    }

    function renderAnnotations(annotations) {
        annotationList.innerHTML = '';
        if (annotations.length === 0) {
            annotationList.innerHTML = '<p style="color: #6b7280; text-align: center; margin-top: 2rem;">No notes yet. Start writing below!</p>';
            return;
        }

        annotations.forEach(annotation => {
            const card = document.createElement('div');
            card.className = 'annotation-card';
            
            const author = document.createElement('div');
            author.className = 'annotation-author';
            author.textContent = annotation.author_name;
            
            // Add Delete Button
            if (annotation.author_id === CURRENT_USER_ID) {
                const deleteBtn = document.createElement('button');
                deleteBtn.textContent = '🗑️';
                deleteBtn.title = 'Delete Note';
                deleteBtn.style.float = 'right';
                deleteBtn.style.fontSize = '0.9rem';
                deleteBtn.style.color = '#e53e3e';
                deleteBtn.style.background = 'none';
                deleteBtn.style.border = 'none';
                deleteBtn.style.cursor = 'pointer';
                deleteBtn.onclick = () => deleteAnnotation(annotation.id);
                author.appendChild(deleteBtn);
            }

            const content = document.createElement('p');
            content.className = 'annotation-content';
            
            if (annotation.content.includes('[AI]:')) {
                 content.style.whiteSpace = 'pre-wrap'; 
            }
            content.textContent = annotation.content;

            card.appendChild(author);
            card.appendChild(content);

            if (annotation.highlighted_text) {
                const quote = document.createElement('blockquote');
                quote.className = 'annotation-highlight';
                quote.textContent = annotation.highlighted_text;
                // Append page number if available
                if(annotation.position_data) {
                    const pageSpan = document.createElement('span');
                    pageSpan.style.display = 'block';
                    pageSpan.style.marginTop = '5px';
                    pageSpan.style.fontSize = '0.75rem';
                    pageSpan.style.color = '#a0aec0';
                    pageSpan.textContent = `(Location: ${annotation.position_data})`;
                    quote.appendChild(pageSpan);
                }
                card.appendChild(quote);
            }
            
            annotationList.appendChild(card);
        });
        
        annotationList.scrollTop = annotationList.scrollHeight;
    }

    async function saveAnnotation() {
        const content = annotationTextarea.value.trim();
        if (!content) { alert('Please write a note.'); return; }
        if (!currentLayerId) { alert('Please select a journal layer.'); return; }

        const highlightedText = currentHighlightedText;
        const positionData = `Page ${currentPageNum}`; // Uses the live page number!

        try {
            const response = await fetch('/api/annotation/new', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: content,
                    layer_id: currentLayerId,
                    highlighted_text: highlightedText,
                    position_data: positionData
                }),
            });

            if (!response.ok) throw new Error('Failed to save');
            
            fetchAnnotations(currentLayerId);
            annotationTextarea.value = '';
            currentHighlightedText = "";
            
        } catch (error) {
            console.error(error);
            alert('Error saving note.');
        }
    }
    
    async function deleteAnnotation(annotationId) {
        if (!confirm('Delete this note?')) return;
        await fetch(`/api/annotation/${annotationId}/delete`, { method: 'POST' });
        const card = document.querySelector(`.annotation-card[data-id="${annotationId}"]`);
        if (card) card.remove();
    }
    
    // --- Modal Logic for Layer Creation ---
    async function openCreateLayerModal() {
        newLayerNameInput.value = '';
        newLayerGroupSelect.innerHTML = '<option value="">Loading groups...</option>';
        createLayerModal.style.display = 'flex';

        try {
            const response = await fetch('/api/user/groups');
            if (!response.ok) throw new Error("Could not fetch groups.");
            const userGroups = await response.json();

            newLayerGroupSelect.innerHTML = '<option value="0">🔒 Private / Public (Everyone)</option>';
            userGroups.forEach(group => {
                const opt = document.createElement('option');
                opt.value = group.id;
                opt.textContent = `👥 Group: ${group.name}`;
                newLayerGroupSelect.appendChild(opt);
            });

        } catch (error) {
            console.error(error);
            alert('Error loading groups.');
            createLayerModal.style.display = 'none';
        }
    }

    confirmLayerBtn.onclick = async () => {
        const layerName = newLayerNameInput.value.trim();
        const groupIdVal = newLayerGroupSelect.value;

        if (!layerName) {
            alert("Please enter a name.");
            return;
        }

        const studyGroupId = (groupIdVal === "0") ? null : parseInt(groupIdVal);

        try {
            const createResponse = await fetch('/api/layer/new', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: layerName,
                    ebook_id: EBOOK_ID,
                    study_group_id: studyGroupId
                }),
            });

            if (!createResponse.ok) throw new Error('Failed to create layer');

            createLayerModal.style.display = 'none';
            await fetchLayers(); 
            
            const newLayer = await createResponse.json();
            layerSelect.value = newLayer.id;
            fetchAnnotations(newLayer.id);

        } catch (error) {
            console.error(error);
            alert('Error creating layer.');
        }
    };

    cancelLayerBtn.onclick = () => {
        createLayerModal.style.display = 'none';
    };


    // --- Ask AI Logic ---
    async function askAiToExplain() {
        const userThought = annotationTextarea.value.trim();
        if (!userThought) {
            alert("Please write a question or thought in the box first.");
            return;
        }

        const originalText = askAiBtn.textContent;
        askAiBtn.textContent = "Thinking...";
        askAiBtn.disabled = true;

        try {
            const response = await fetch('/api/ai/explain', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    text: userThought,
                    ebook_id: EBOOK_ID 
                })
            });
            
            const data = await response.json();
            
            // Append Answer
            annotationTextarea.value += `\n\n[AI]: ${data.explanation}\n`;
            annotationTextarea.scrollTop = annotationTextarea.scrollHeight;
            
        } catch (error) {
            console.error("AI Error:", error);
            alert("AI could not respond.");
        } finally {
            askAiBtn.textContent = "✨ Ask AI";
            askAiBtn.disabled = false;
            askAiBtn.style.animation = "none"; 
        }
    }

    // --- Event Listeners ---
    layerSelect.addEventListener('change', (e) => fetchAnnotations(e.target.value));
    saveAnnotationBtn.addEventListener('click', saveAnnotation);
    
    addLayerBtn.addEventListener('click', openCreateLayerModal);
    
    if (askAiBtn) {
        askAiBtn.addEventListener('click', askAiToExplain);
    }
    
    // Simple Page Navigation (Updates scroll position)
    prevPageBtn.addEventListener('click', () => { 
        // Find current page wrapper and scroll to previous one
        const prevWrapper = document.getElementById(`page-wrapper-${currentPageNum - 1}`);
        if (prevWrapper) prevWrapper.scrollIntoView({behavior: "smooth"});
    });
    nextPageBtn.addEventListener('click', () => { 
        const nextWrapper = document.getElementById(`page-wrapper-${currentPageNum + 1}`);
        if (nextWrapper) nextWrapper.scrollIntoView({behavior: "smooth"});
    });

    // Close modal on click outside
    createLayerModal.addEventListener('click', (e) => {
        if (e.target === createLayerModal) createLayerModal.style.display = 'none';
    });

    // --- Init ---
    fetchLayers();
    loadPdf(PDF_URL);
});