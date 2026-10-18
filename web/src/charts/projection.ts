// The Natural Earth projection (as d3-geo's geoNaturalEarth1, and the world map of the old app), in
// the {project, unproject} form ECharts takes for maps. Coordinates in degrees; y grows downward.

const RAD = Math.PI / 180

function forward(lambda: number, phi: number): [number, number] {
  const phi2 = phi * phi, phi4 = phi2 * phi2
  return [
    lambda * (0.8707 - 0.131979 * phi2 + phi4 * (-0.013791 + phi4 * (0.003971 * phi2 - 0.001529 * phi4))),
    phi * (1.007226 + phi2 * (0.015085 + phi4 * (-0.044475 + 0.028874 * phi2 - 0.005916 * phi4))),
  ]
}

function inverse(x: number, y: number): [number, number] {
  let phi = y, delta = 0, i = 25
  do {
    const phi2 = phi * phi, phi4 = phi2 * phi2
    delta = (phi * (1.007226 + phi2 * (0.015085 + phi4 * (-0.044475 + 0.028874 * phi2 - 0.005916 * phi4))) - y)
      / (1.007226 + phi2 * (0.015085 * 3 + phi4 * (-0.044475 * 7 + 0.028874 * 9 * phi2 - 0.005916 * 11 * phi4)))
    phi -= delta
  } while (Math.abs(delta) > 1e-6 && --i > 0)
  const phi2 = phi * phi
  return [x / (0.8707 + phi2 * (-0.131979 + phi2 * (-0.013791 + phi2 * phi2 * phi2 * (0.003971 - 0.001529 * phi2)))), phi]
}

export const NATURAL_EARTH = {
  project: (point: number[]): number[] => {
    const [x, y] = forward(point[0] * RAD, point[1] * RAD)
    return [x, -y]
  },
  unproject: (point: number[]): number[] => {
    const [lambda, phi] = inverse(point[0], -point[1])
    return [lambda / RAD, phi / RAD]
  },
}
