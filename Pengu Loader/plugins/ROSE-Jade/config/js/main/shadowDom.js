export function currentBorder(element) {
    const root = element.shadowRoot;
    const rootStyle = document.createElement("style");
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
			background-image: var(--current-border);
		}
    `;
    root.appendChild(rootStyle);
}