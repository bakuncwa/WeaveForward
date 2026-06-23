var FIBER_COLORS = {
    acrylic:'#ff6b6b', alpaca:'#d2b48c', bamboo:'#81c784', cashmere:'#cfd8dc',
    cotton:'#f5f0e0', denim:'#1565c0', elastane:'#666', hemp:'#6b8e23',
    linen:'#e8d5b7', lyocell:'#a5d6a7', modal:'#e0e0e0', nylon:'#90caf9',
    polyester:'#b0b0b0', rayon:'#a5d6a7', silk:'#c9a96e', tencel:'#80cbc4',
    viscose:'#bcaaa4', wool:'#8b7355',
};

function fiberSwatchHtml(name) {
    var c = FIBER_COLORS[(name||'').toLowerCase()] || '#ccc';
    return '<span class="fiber-swatch" style="background:' + c + '"></span>';
}
