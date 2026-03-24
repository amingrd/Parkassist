figma.showUI(__html__, { width: 420, height: 520 });

async function ensureFont(node) {
  if (node.fontName && node.fontName !== figma.mixed) {
    await figma.loadFontAsync(node.fontName);
  }
}

async function applyPayload(payload) {
  const variants = [];
  for (const variant of payload.variants) {
    const source = figma.currentPage.findOne((node) => node.type === "FRAME" && node.name === variant.frame_name);
    if (!source) {
      throw new Error(`Missing frame: ${variant.frame_name}`);
    }
    const clone = source.clone();
    clone.name = `${variant.frame_name} / Export`;

    const headlineNode = clone.findOne((node) => node.type === "TEXT" && node.name === payload.figma_nodes.headline);
    const sublineNode = clone.findOne((node) => node.type === "TEXT" && node.name === payload.figma_nodes.subline);
    const buttonNode = clone.findOne((node) => node.type === "TEXT" && node.name === payload.figma_nodes.button_text);
    if (!headlineNode || !sublineNode || !buttonNode) {
      throw new Error(`Missing mapped text node in ${variant.frame_name}`);
    }

    await ensureFont(headlineNode);
    await ensureFont(sublineNode);
    await ensureFont(buttonNode);
    headlineNode.characters = payload.fields.headline;
    sublineNode.characters = payload.fields.subline;
    buttonNode.characters = payload.fields.button_text;

    const bytes = await clone.exportAsync({ format: "PNG" });
    variants.push({
      name: variant.export_name,
      bytes: Array.from(bytes)
    });
    clone.remove();
  }
  figma.ui.postMessage({ type: "export-complete", variants });
}

figma.ui.onmessage = async (message) => {
  if (message.type === "apply-payload") {
    try {
      await applyPayload(message.payload);
    } catch (error) {
      figma.ui.postMessage({ type: "export-error", message: String(error) });
    }
  }
  if (message.type === "close") {
    figma.closePlugin();
  }
};
