export interface Canva {
	v: string;
	p: {
		layers: {
			name: string;
			visible: boolean;
			selectable: boolean;
			movable: boolean;
			editable: boolean;
		}[];
		autoAdjustIndex: boolean;
		hierarchicalRendering: boolean;
	};
	a: {
		width: number;
		fitContent: boolean;
		rectSelectable: boolean;
		pannable: boolean;
		zoomable: boolean;
		height: number;
	};
	d: any[];
	contentRect: {
		x: number;
		y: number;
		width: number;
		height: number;
	};
}
