export function currentBorder(element) {
	const root = element.shadowRoot;
	if (!root) {
		return;
	}

	// Only inject style if border plugin is enabled
	if (window.CONFIG && !window.CONFIG.regaliaBorderEnabled) {
		return;
	}

	// If no custom border is selected, do NOT override the default emblem visuals.
	// `var(--current-border, unset)` can clear the default emblem/background and
	// make the rank look like it "disappeared" even when the user didn't choose
	// a border yet.
	const hasSelectedBorder =
		!!document.documentElement?.style?.getPropertyValue?.('--current-border') ||
		!!getComputedStyle(document.documentElement).getPropertyValue('--current-border').trim();
	if (!hasSelectedBorder) {
		return;
	}

	const rootStyle = document.createElement("style");
	rootStyle.className = "jade-border-style"; // Add class for easy removal
	rootStyle.textContent = `
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="unranked"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="iron"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="bronze"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="silver"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="gold"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="platinum"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="emerald"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="diamond"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="master"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="grandmaster"],
		:host .regalia-emblem-container .regalia-emblem[ranked-tier="challenger"]
		{
			background-image: var(--current-border, unset);
		}
	`;
	root.appendChild(rootStyle);
}

// Function to remove border styles when plugin is disabled
export function removeBorderStyles() {
	const elements = document.querySelectorAll('lol-regalia-emblem-element');
	elements.forEach(element => {
		if (element.shadowRoot) {
			const style = element.shadowRoot.querySelector('style.jade-border-style');
			if (style) {
				style.remove();
			}
		}
	});
}