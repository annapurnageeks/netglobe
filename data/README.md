# Bundled data

All offline, all from public sources. netglobe never looks anything up online.

- **landmask.json** — a 180×90 land/sea grid for drawing the globe, rasterized from [Natural Earth](https://www.naturalearthdata.com/) 110m land (public domain).
- **ip2country.json / ip2country6.json** — IPv4 and IPv6 address ranges to country codes, built from the [RIR](https://www.nro.net/about/rirs/) delegation files (public), gzip-packed.
- **countries.json** — country code to name and centroid lat/lon, from [eesur/country-codes-lat-long](https://github.com/eesur/country-codes-lat-long).

These change slowly; rebuild them from the latest sources if you want. The build steps are in the project history.
