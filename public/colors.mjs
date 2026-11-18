import ColorHash from './vendor/color-hash-2.0.2/color-hash.mjs';

const colorHash = new ColorHash({ saturation: [0.58, 0.66, 0.74], lightness: 0.42 });

export function identityColors(kind, id) {
  const [hue, saturation] = colorHash.hsl(`${kind}:${id}`);
  const color = light => `hsl(${hue} ${Math.round(saturation * 100)}% ${light}%)`;
  return {
    accent: color(74),
    surface: color(14),
    border: color(32),
    ink: color(82),
  };
}
