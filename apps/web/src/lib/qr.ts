/**
 * Self-contained QR code generator (no external dependency, no network / no
 * external QR API).
 *
 * This is a compact TypeScript port of the well-known, public-domain
 * `qrcode-generator` algorithm by Kazuhiko Arase (MIT). It supports 8-bit byte
 * mode with automatic version selection, which is all a Passport/Card URL needs.
 * We keep the version table up to version 10 (≈270 data codewords at EC level M)
 * — far more than any `{app}/card/{slug}` URL requires — and fail loudly if a
 * caller ever exceeds that.
 *
 * The only export used by the app is {@link generateQrMatrix}, which returns a
 * square boolean matrix (`true` = dark module) that the QrCode component paints
 * as an inline SVG.
 */

// ── Error correction levels ──────────────────────────────────────────────────
export type QrErrorCorrectionLevel = "L" | "M" | "Q" | "H"
// Format-info EC indicator bits (spec §8.9): L=01, M=00, Q=11, H=10. ONLY for
// the encoded type-info — never a table index.
const EC_LEVEL_VALUE: Record<QrErrorCorrectionLevel, number> = { M: 0, L: 1, H: 2, Q: 3 }
// Row order of RS_BLOCK_TABLE per version. Indexing that table with the
// format-info bit values instead produced structurally corrupt codes: an "M"
// QR was built with L's Reed-Solomon block layout while its format info
// claimed M, so real scanners could never decode it (VBR-RRO-D002).
const EC_ROW_INDEX: Record<QrErrorCorrectionLevel, number> = { L: 0, M: 1, Q: 2, H: 3 }

// ── GF(256) math ─────────────────────────────────────────────────────────────
const EXP_TABLE: number[] = new Array(256)
const LOG_TABLE: number[] = new Array(256)
for (let i = 0; i < 8; i += 1) EXP_TABLE[i] = 1 << i
for (let i = 8; i < 256; i += 1) {
  EXP_TABLE[i] = EXP_TABLE[i - 4] ^ EXP_TABLE[i - 5] ^ EXP_TABLE[i - 6] ^ EXP_TABLE[i - 8]
}
for (let i = 0; i < 255; i += 1) LOG_TABLE[EXP_TABLE[i]] = i

function gexp(n: number): number {
  let m = n
  while (m < 0) m += 255
  while (m >= 256) m -= 255
  return EXP_TABLE[m]
}
function glog(n: number): number {
  if (n < 1) throw new Error(`glog(${n})`)
  return LOG_TABLE[n]
}

// ── Polynomial over GF(256) ──────────────────────────────────────────────────
function polyMultiply(a: number[], b: number[]): number[] {
  const num = new Array(a.length + b.length - 1).fill(0)
  for (let i = 0; i < a.length; i += 1) {
    for (let j = 0; j < b.length; j += 1) {
      num[i + j] ^= gexp(glog(a[i]) + glog(b[j]))
    }
  }
  return num
}
function polyMod(self: number[], divisor: number[]): number[] {
  if (self.length - divisor.length < 0) return self
  const ratio = glog(self[0]) - glog(divisor[0])
  const num = self.slice()
  for (let i = 0; i < divisor.length; i += 1) {
    num[i] ^= gexp(glog(divisor[i]) + ratio)
  }
  // Drop leading zeros then recurse.
  let start = 0
  while (start < num.length && num[start] === 0) start += 1
  return polyMod(num.slice(start), divisor)
}
function errorCorrectPolynomial(ecLength: number): number[] {
  let poly = [1]
  for (let i = 0; i < ecLength; i += 1) poly = polyMultiply(poly, [1, gexp(i)])
  return poly
}

// ── Spec tables ──────────────────────────────────────────────────────────────
// Alignment pattern centre positions per version (index = version - 1).
const PATTERN_POSITION_TABLE: number[][] = [
  [], [6, 18], [6, 22], [6, 26], [6, 30],
  [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
]

// RS block table, rows ordered [L, M, Q, H] per version. Each row is a flat list
// of [blockCount, totalCount, dataCount] triples (multiple triples = mixed blocks).
const RS_BLOCK_TABLE: number[][] = [
  // v1
  [1, 26, 19], [1, 26, 16], [1, 26, 13], [1, 26, 9],
  // v2
  [1, 44, 34], [1, 44, 28], [1, 44, 22], [1, 44, 16],
  // v3
  [1, 70, 55], [1, 70, 44], [2, 35, 17], [2, 35, 13],
  // v4
  [1, 100, 80], [2, 50, 32], [2, 50, 24], [4, 25, 9],
  // v5
  [1, 134, 108], [2, 67, 43], [2, 33, 15, 2, 34, 16], [2, 33, 11, 2, 34, 12],
  // v6
  [2, 86, 68], [4, 43, 27], [4, 43, 19], [4, 43, 15],
  // v7
  [2, 98, 78], [4, 49, 31], [2, 32, 14, 4, 33, 15], [4, 39, 13, 1, 40, 14],
  // v8
  [2, 121, 97], [2, 60, 38, 2, 61, 39], [4, 40, 18, 2, 41, 19], [4, 40, 14, 2, 41, 15],
  // v9
  [2, 146, 116], [3, 58, 36, 2, 59, 37], [4, 36, 16, 4, 37, 17], [4, 36, 12, 4, 37, 13],
  // v10
  [2, 86, 68, 2, 87, 69], [4, 69, 43, 1, 70, 44], [6, 43, 19, 2, 44, 20], [6, 43, 15, 2, 44, 16],
]

type RsBlock = { totalCount: number; dataCount: number }
function getRsBlocks(version: number, ecLevel: QrErrorCorrectionLevel): RsBlock[] {
  const row = RS_BLOCK_TABLE[(version - 1) * 4 + EC_ROW_INDEX[ecLevel]]
  if (!row) throw new Error(`Unsupported QR version ${version}`)
  const blocks: RsBlock[] = []
  for (let i = 0; i < row.length; i += 3) {
    const count = row[i]
    const totalCount = row[i + 1]
    const dataCount = row[i + 2]
    for (let j = 0; j < count; j += 1) blocks.push({ totalCount, dataCount })
  }
  return blocks
}

// ── BCH type info / type number ──────────────────────────────────────────────
const G15 = (1 << 10) | (1 << 8) | (1 << 5) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0)
const G18 = (1 << 12) | (1 << 11) | (1 << 10) | (1 << 9) | (1 << 8) | (1 << 5) | (1 << 2) | (1 << 0)
const G15_MASK = (1 << 14) | (1 << 12) | (1 << 10) | (1 << 4) | (1 << 1)

function bchDigit(dataIn: number): number {
  let data = dataIn
  let digit = 0
  while (data !== 0) {
    digit += 1
    data >>>= 1
  }
  return digit
}
function getBchTypeInfo(data: number): number {
  let d = data << 10
  while (bchDigit(d) - bchDigit(G15) >= 0) d ^= G15 << (bchDigit(d) - bchDigit(G15))
  return ((data << 10) | d) ^ G15_MASK
}
function getBchTypeNumber(data: number): number {
  let d = data << 12
  while (bchDigit(d) - bchDigit(G18) >= 0) d ^= G18 << (bchDigit(d) - bchDigit(G18))
  return (data << 12) | d
}

// ── Mask functions ───────────────────────────────────────────────────────────
const MASK_FUNCS: Array<(i: number, j: number) => boolean> = [
  (i, j) => (i + j) % 2 === 0,
  (i) => i % 2 === 0,
  (_i, j) => j % 3 === 0,
  (i, j) => (i + j) % 3 === 0,
  (i, j) => (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0,
  (i, j) => ((i * j) % 2) + ((i * j) % 3) === 0,
  (i, j) => (((i * j) % 2) + ((i * j) % 3)) % 2 === 0,
  (i, j) => (((i * j) % 3) + ((i + j) % 2)) % 2 === 0,
]

// 8-bit byte length header is 8 bits for versions 1–9, 16 bits for 10+.
function lengthInBits(version: number): number {
  return version <= 9 ? 8 : 16
}

// ── Bit buffer ───────────────────────────────────────────────────────────────
class BitBuffer {
  buffer: number[] = []
  length = 0
  put(num: number, len: number) {
    for (let i = 0; i < len; i += 1) this.putBit(((num >>> (len - i - 1)) & 1) === 1)
  }
  putBit(bit: boolean) {
    const bufIndex = Math.floor(this.length / 8)
    if (this.buffer.length <= bufIndex) this.buffer.push(0)
    if (bit) this.buffer[bufIndex] |= 0x80 >>> this.length % 8
    this.length += 1
  }
}

// ── UTF-8 byte encoding of the payload ───────────────────────────────────────
function utf8Bytes(text: string): number[] {
  const out: number[] = []
  for (let i = 0; i < text.length; i += 1) {
    let code = text.charCodeAt(i)
    if (code < 0x80) {
      out.push(code)
    } else if (code < 0x800) {
      out.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f))
    } else if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) {
      // Surrogate pair.
      const next = text.charCodeAt(i + 1)
      code = 0x10000 + ((code - 0xd800) << 10) + (next - 0xdc00)
      i += 1
      out.push(0xf0 | (code >> 18), 0x80 | ((code >> 12) & 0x3f), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f))
    } else {
      out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f))
    }
  }
  return out
}

// ── Interleaved data + EC codewords ──────────────────────────────────────────
function createData(version: number, ecLevel: QrErrorCorrectionLevel, data: number[]): number[] {
  const buffer = new BitBuffer()
  buffer.put(4, 4) // 8-bit byte mode indicator.
  buffer.put(data.length, lengthInBits(version))
  for (const b of data) buffer.put(b, 8)

  const blocks = getRsBlocks(version, ecLevel)
  const totalDataCount = blocks.reduce((sum, b) => sum + b.dataCount, 0)
  if (buffer.length > totalDataCount * 8) {
    throw new Error(`QR content too long: ${buffer.length} > ${totalDataCount * 8} bits`)
  }
  if (buffer.length + 4 <= totalDataCount * 8) buffer.put(0, 4) // Terminator.
  while (buffer.length % 8 !== 0) buffer.putBit(false)
  // Pad bytes.
  const PAD0 = 0xec
  const PAD1 = 0x11
  while (true) {
    if (buffer.length >= totalDataCount * 8) break
    buffer.put(PAD0, 8)
    if (buffer.length >= totalDataCount * 8) break
    buffer.put(PAD1, 8)
  }

  // Split into data blocks, compute EC, interleave.
  let offset = 0
  let maxDc = 0
  let maxEc = 0
  const dcData: number[][] = []
  const ecData: number[][] = []
  for (const block of blocks) {
    const dcCount = block.dataCount
    const ecCount = block.totalCount - block.dataCount
    maxDc = Math.max(maxDc, dcCount)
    maxEc = Math.max(maxEc, ecCount)
    const dc = new Array(dcCount)
    for (let i = 0; i < dcCount; i += 1) dc[i] = 0xff & buffer.buffer[i + offset]
    offset += dcCount
    const rsPoly = errorCorrectPolynomial(ecCount)
    const rawPoly = dc.concat(new Array(rsPoly.length - 1).fill(0))
    const modPoly = polyMod(rawPoly, rsPoly)
    const ec = new Array(rsPoly.length - 1)
    for (let i = 0; i < ec.length; i += 1) {
      const modIndex = i + modPoly.length - ec.length
      ec[i] = modIndex >= 0 ? modPoly[modIndex] : 0
    }
    dcData.push(dc)
    ecData.push(ec)
  }

  const result: number[] = []
  for (let i = 0; i < maxDc; i += 1) {
    for (let b = 0; b < blocks.length; b += 1) {
      if (i < dcData[b].length) result.push(dcData[b][i])
    }
  }
  for (let i = 0; i < maxEc; i += 1) {
    for (let b = 0; b < blocks.length; b += 1) {
      if (i < ecData[b].length) result.push(ecData[b][i])
    }
  }
  return result
}

// ── Module matrix construction ───────────────────────────────────────────────
type Grid = Array<Array<boolean | null>>

function makeGrid(size: number): Grid {
  return Array.from({ length: size }, () => new Array<boolean | null>(size).fill(null))
}

function setupFinder(grid: Grid, row: number, col: number) {
  const size = grid.length
  for (let r = -1; r <= 7; r += 1) {
    if (row + r <= -1 || size <= row + r) continue
    for (let c = -1; c <= 7; c += 1) {
      if (col + c <= -1 || size <= col + c) continue
      const dark =
        (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
        (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
        (r >= 2 && r <= 4 && c >= 2 && c <= 4)
      grid[row + r][col + c] = dark
    }
  }
}

function setupTiming(grid: Grid) {
  const size = grid.length
  for (let i = 8; i < size - 8; i += 1) {
    if (grid[i][6] === null) grid[i][6] = i % 2 === 0
    if (grid[6][i] === null) grid[6][i] = i % 2 === 0
  }
}

function setupAlignment(grid: Grid, version: number) {
  const pos = PATTERN_POSITION_TABLE[version - 1]
  for (const row of pos) {
    for (const col of pos) {
      if (grid[row][col] !== null) continue
      for (let r = -2; r <= 2; r += 1) {
        for (let c = -2; c <= 2; c += 1) {
          grid[row + r][col + c] = r === -2 || r === 2 || c === -2 || c === 2 || (r === 0 && c === 0)
        }
      }
    }
  }
}

function setupTypeInfo(grid: Grid, ecLevel: QrErrorCorrectionLevel, maskPattern: number) {
  const size = grid.length
  const data = (EC_LEVEL_VALUE[ecLevel] << 3) | maskPattern
  const bits = getBchTypeInfo(data)
  for (let i = 0; i < 15; i += 1) {
    const mod = ((bits >> i) & 1) === 1
    // Vertical (top-left + bottom-left).
    if (i < 6) grid[i][8] = mod
    else if (i < 8) grid[i + 1][8] = mod
    else grid[size - 15 + i][8] = mod
    // Horizontal (top-left + top-right).
    if (i < 8) grid[8][size - i - 1] = mod
    else if (i < 9) grid[8][15 - i - 1 + 1] = mod
    else grid[8][15 - i - 1] = mod
  }
  grid[size - 8][8] = true // Fixed dark module.
}

function setupTypeNumber(grid: Grid, version: number) {
  if (version < 7) return
  const size = grid.length
  const bits = getBchTypeNumber(version)
  for (let i = 0; i < 18; i += 1) {
    const mod = ((bits >> i) & 1) === 1
    grid[Math.floor(i / 3)][size - 8 - 3 + (i % 3)] = mod
    grid[size - 8 - 3 + (i % 3)][Math.floor(i / 3)] = mod
  }
}

function mapData(grid: Grid, data: number[], maskPattern: number) {
  const size = grid.length
  const maskFn = MASK_FUNCS[maskPattern]
  let inc = -1
  let row = size - 1
  let bitIndex = 7
  let byteIndex = 0
  for (let col = size - 1; col > 0; col -= 2) {
    if (col === 6) col -= 1
    while (true) {
      for (let c = 0; c < 2; c += 1) {
        if (grid[row][col - c] === null) {
          let dark = false
          if (byteIndex < data.length) dark = ((data[byteIndex] >>> bitIndex) & 1) === 1
          if (maskFn(row, col - c)) dark = !dark
          grid[row][col - c] = dark
          bitIndex -= 1
          if (bitIndex === -1) {
            byteIndex += 1
            bitIndex = 7
          }
        }
      }
      row += inc
      if (row < 0 || size <= row) {
        row -= inc
        inc = -inc
        break
      }
    }
  }
}

// Penalty scoring for automatic mask selection.
function lostPoint(grid: Grid): number {
  const size = grid.length
  const dark = (r: number, c: number) => grid[r][c] === true
  let lost = 0
  // Rule 1: runs of same-colour modules in rows/cols.
  for (let r = 0; r < size; r += 1) {
    for (let c = 0; c < size; c += 1) {
      let sameCount = 0
      const self = dark(r, c)
      for (let dr = -1; dr <= 1; dr += 1) {
        if (r + dr < 0 || size <= r + dr) continue
        for (let dc = -1; dc <= 1; dc += 1) {
          if (c + dc < 0 || size <= c + dc || (dr === 0 && dc === 0)) continue
          if (self === dark(r + dr, c + dc)) sameCount += 1
        }
      }
      if (sameCount > 5) lost += 3 + sameCount - 5
    }
  }
  // Rule 2: 2x2 blocks.
  for (let r = 0; r < size - 1; r += 1) {
    for (let c = 0; c < size - 1; c += 1) {
      let count = 0
      if (dark(r, c)) count += 1
      if (dark(r + 1, c)) count += 1
      if (dark(r, c + 1)) count += 1
      if (dark(r + 1, c + 1)) count += 1
      if (count === 0 || count === 4) lost += 3
    }
  }
  // Rule 3: finder-like patterns.
  for (let r = 0; r < size; r += 1) {
    for (let c = 0; c < size - 6; c += 1) {
      if (
        dark(r, c) && !dark(r, c + 1) && dark(r, c + 2) && dark(r, c + 3) &&
        dark(r, c + 4) && !dark(r, c + 5) && dark(r, c + 6)
      ) lost += 40
    }
  }
  for (let c = 0; c < size; c += 1) {
    for (let r = 0; r < size - 6; r += 1) {
      if (
        dark(r, c) && !dark(r + 1, c) && dark(r + 2, c) && dark(r + 3, c) &&
        dark(r + 4, c) && !dark(r + 5, c) && dark(r + 6, c)
      ) lost += 40
    }
  }
  // Rule 4: dark-module balance.
  let darkCount = 0
  for (let r = 0; r < size; r += 1) for (let c = 0; c < size; c += 1) if (dark(r, c)) darkCount += 1
  const ratio = Math.abs((100 * darkCount) / (size * size) - 50) / 5
  lost += Math.floor(ratio) * 10
  return lost
}

function buildMatrix(version: number, ecLevel: QrErrorCorrectionLevel, data: number[], maskPattern: number): Grid {
  const size = version * 4 + 17
  const grid = makeGrid(size)
  setupFinder(grid, 0, 0)
  setupFinder(grid, size - 7, 0)
  setupFinder(grid, 0, size - 7)
  setupAlignment(grid, version)
  setupTiming(grid)
  setupTypeInfo(grid, ecLevel, maskPattern)
  setupTypeNumber(grid, version)
  mapData(grid, data, maskPattern)
  return grid
}

function chooseVersion(byteLength: number, ecLevel: QrErrorCorrectionLevel): number {
  for (let version = 1; version <= 10; version += 1) {
    const blocks = getRsBlocks(version, ecLevel)
    const totalDataCount = blocks.reduce((sum, b) => sum + b.dataCount, 0)
    // Available data bits minus mode (4) + length header.
    const availableBits = totalDataCount * 8 - 4 - lengthInBits(version)
    if (byteLength * 8 <= availableBits) return version
  }
  throw new Error("QR content exceeds supported capacity (version 10, level M/L).")
}

/**
 * Encode `text` into a square QR module matrix (`true` = dark). Byte mode with
 * automatic version selection and best-mask scoring. Level "M" by default — the
 * standard balance of density and error tolerance for a scannable link.
 */
export function generateQrMatrix(text: string, ecLevel: QrErrorCorrectionLevel = "M"): boolean[][] {
  const bytes = utf8Bytes(text)
  const version = chooseVersion(bytes.length, ecLevel)
  const data = createData(version, ecLevel, bytes)

  // Try every mask; keep the lowest-penalty result (spec §8.8.2).
  let best: Grid | null = null
  let bestScore = Number.POSITIVE_INFINITY
  for (let mask = 0; mask < 8; mask += 1) {
    const grid = buildMatrix(version, ecLevel, data, mask)
    const score = lostPoint(grid)
    if (score < bestScore) {
      bestScore = score
      best = grid
    }
  }
  // Every module is assigned by construction, so the cast is safe.
  return (best as Grid).map((row) => row.map((cell) => cell === true))
}
