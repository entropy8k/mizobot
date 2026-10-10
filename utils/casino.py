"""Pure casino logic (no Discord imports): blackjack, mines, limbo and dice.

Every game uses OS randomness and a 3% house edge (97% return to player), except blackjack,
which uses standard rules (dealer stands on all 17s, blackjack pays 3:2, double down on first two cards).
"""
import math
import random

rng = random.SystemRandom()
EDGE = 0.03
MIN_BET = 10


def parse_amount(raw, balance):
    """'500', '2k', '1.5m', 'half', 'all' -> int, or None if unparsable."""
    raw = str(raw).lower().replace(",", "").replace("_", "").strip()
    if raw == "all":
        return balance
    if raw == "half":
        return balance // 2
    mult = 1
    if raw.endswith("k"):
        raw, mult = raw[:-1], 1_000
    elif raw.endswith("m"):
        raw, mult = raw[:-1], 1_000_000
    try:
        return int(float(raw) * mult)
    except (ValueError, OverflowError):
        return None


# ------------------------------------------------------------- blackjack
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]


def card_value(rank):
    return 11 if rank == "A" else 10 if rank in ("J", "Q", "K") else int(rank)


def hand_value(cards):
    total = sum(card_value(r) for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards):
    return len(cards) == 2 and hand_value(cards) == 21


def fmt_card(card):
    return f"{card[0]}{card[1]}"


class Blackjack:
    """outcome: blackjack | win | push | lose | bust (set once `over` is True)."""

    def __init__(self, bet):
        self.bet = bet
        self.deck = [(r, s) for r in RANKS for s in SUITS]
        rng.shuffle(self.deck)
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]
        self.doubled = False
        self.over = False
        self.outcome = None
        p, d = is_blackjack(self.player), is_blackjack(self.dealer)
        if p and d:
            self._end("push")
        elif p:
            self._end("blackjack")
        elif d:
            self._end("lose")

    @property
    def total_bet(self):
        return self.bet * 2 if self.doubled else self.bet

    def _end(self, outcome):
        self.over, self.outcome = True, outcome

    def hit(self):
        assert not self.over
        self.player.append(self.deck.pop())
        v = hand_value(self.player)
        if v > 21:
            self._end("bust")
        elif v == 21:
            self.stand()

    def stand(self):
        assert not self.over
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        pv, dv = hand_value(self.player), hand_value(self.dealer)
        self._end("win" if dv > 21 or pv > dv else "push" if pv == dv else "lose")

    def can_double(self):
        return not self.over and len(self.player) == 2 and not self.doubled

    def double(self):
        assert self.can_double()
        self.doubled = True
        self.player.append(self.deck.pop())
        if hand_value(self.player) > 21:
            self._end("bust")
        else:
            self.stand()

    def payout(self):
        """Total returned to the player (stake included)."""
        assert self.over
        if self.outcome == "blackjack":
            return self.bet + self.bet * 3 // 2
        if self.outcome == "win":
            return self.total_bet * 2
        if self.outcome == "push":
            return self.total_bet
        return 0


# ----------------------------------------------------------------- mines
MINES_TILES = 20          # 5 x 4 grid (Discord's 25-component limit leaves room for a Cash Out button)
MINES_MAX_BOMBS = MINES_TILES - 1


def mines_multiplier(safe_found, bombs):
    """Fair multiplier for surviving `safe_found` reveals, minus the house edge."""
    if safe_found == 0:
        return 1.0
    p = 1.0
    for i in range(safe_found):
        p *= (MINES_TILES - bombs - i) / (MINES_TILES - i)
    return (1 - EDGE) / p


class Mines:
    def __init__(self, bet, bombs):
        assert 1 <= bombs <= MINES_MAX_BOMBS
        self.bet, self.bombs = bet, bombs
        self.bomb_tiles = set(rng.sample(range(MINES_TILES), bombs))   # fixed up front
        self.revealed = set()
        self.over = False
        self.hit_bomb = False

    @property
    def safe_total(self):
        return MINES_TILES - self.bombs

    @property
    def multiplier(self):
        return mines_multiplier(len(self.revealed), self.bombs)

    @property
    def next_multiplier(self):
        return mines_multiplier(len(self.revealed) + 1, self.bombs)

    def cashout_value(self):
        return int(self.bet * self.multiplier)

    def reveal(self, tile):
        """-> 'bomb' | 'safe' | 'cleared' (all safe tiles found) | 'ignored'."""
        if self.over or tile in self.revealed:
            return "ignored"
        if tile in self.bomb_tiles:
            self.over = self.hit_bomb = True
            return "bomb"
        self.revealed.add(tile)
        if len(self.revealed) == self.safe_total:
            self.over = True
            return "cleared"
        return "safe"

    def payout(self):
        return 0 if self.hit_bomb else self.cashout_value()


# ----------------------------------------------------------------- limbo
LIMBO_MIN, LIMBO_MAX = 1.01, 1000.0


def limbo_roll():
    """Crash-style multiplier with P(result >= t) = (1 - EDGE) / t."""
    u = 1.0 - rng.random()                       # (0, 1]
    return max(1.0, min(math.floor((1 - EDGE) / u * 100) / 100, 1_000_000.0))


def limbo_chance(target):
    return min(1.0, (1 - EDGE) / target)


# ------------------------------------------------------------------ dice
# A roll is an integer 0..9999 shown as 0.00 - 99.99. "under T" wins if roll < T, "over T" if roll > T.
def dice_wins(direction, t):
    return t if direction == "under" else 9999 - t


def dice_chance(direction, t):
    return dice_wins(direction, t) / 10_000


def dice_multiplier(direction, t):
    return (1 - EDGE) / dice_chance(direction, t)


def dice_valid(direction, t):
    return 100 <= dice_wins(direction, t) <= 9500     # 1% .. 95% win chance (so a win always pays > 1x)


def dice_roll():
    return rng.randrange(10_000)


def dice_won(direction, t, roll):
    return roll < t if direction == "under" else roll > t
