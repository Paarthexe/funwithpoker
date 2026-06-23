from player import Player, PlayerAction
from card import Card, Rank, Suit
from hand_evaluator import HandEvaluator, HandRank
from collections import defaultdict
import random


class BasicRuleBasedPlayer(Player):

    def __init__(self, name, stack):
        super().__init__(name, stack)
        self.state = "normal"
        self.last_preflop_aggressor = False

    def reset_for_new_hand(self):
        super().reset_for_new_hand()
        self.state = "normal"
        self.last_preflop_aggressor = False

    def action(self, game_state: list[int], action_history: list):
        pot           = game_state[7]
        current_bet   = game_state[8]
        big_blind     = game_state[9]
        active_idx    = game_state[10]
        num_players   = game_state[11]
        call_amount   = max(0, current_bet - self.bet_amount)

        is_in_position = active_idx >= num_players - 2

        comm_cards    = self._parse_community(game_state)
        num_community = sum(1 for c in comm_cards if c is not None)

        if num_community >= 3:
            present = [c for c in comm_cards if c is not None]
            result  = HandEvaluator.evaluate_hand(self.hole_cards, present)

            if result.hand_rank.value >= HandRank.THREE_OF_A_KIND.value:
                self.state = "aggressive"
            elif result.hand_rank.value < HandRank.PAIR.value:
                self.state = "normal"

        if action_history:
            last_phase   = action_history[-1][0]
            raise_counts = defaultdict(int)

            for phase, player, act, _ in action_history:
                if phase == last_phase and act == "raise":
                    raise_counts[player] += 1

            heavy_raisers = [p for p, c in raise_counts.items() if c >= 3]

            if len(heavy_raisers) >= 2 and call_amount > 0:
                return self._call_or_bluff_or_fold(call_amount, pot, big_blind, 0.40)

        if num_community == 0:
            return self._preflop_action(call_amount, pot, big_blind, is_in_position)

        return self._postflop_action(comm_cards, call_amount, pot, big_blind, num_community)

    def _call_or_bluff_or_fold(self, call_amount, pot, big_blind, threshold):
        if self._pot_odds_ok(call_amount, pot, threshold):
            return PlayerAction.CALL, call_amount
        if random.random() < 0.50:
            return self._make_raise_fraction(pot, big_blind, call_amount, 0.50)
        return PlayerAction.FOLD, 0

    def _preflop_action(self, call_amount, pot, big_blind, is_in_position):
        self.last_preflop_aggressor = False

        score = self._chen_score(self.hole_cards[0], self.hole_cards[1])
        effective_score = score + (1.5 if is_in_position else 0)

        if effective_score >= 9:
            self.last_preflop_aggressor = True
            return self._make_raise_fraction(pot, big_blind, call_amount, 0.75)

        if effective_score >= 5:
            if call_amount == 0:
                return PlayerAction.CHECK, 0
            return self._call_or_bluff_or_fold(call_amount, pot, big_blind, 0.40)

        if call_amount == 0:
            return PlayerAction.CHECK, 0
        if random.random() < 0.50:
            return self._make_raise_fraction(pot, big_blind, call_amount, 0.50)
        return PlayerAction.FOLD, 0

    def _postflop_action(self, comm_cards, call_amount, pot, big_blind, num_community):
        present  = [c for c in comm_cards if c is not None]
        result   = HandEvaluator.evaluate_hand(self.hole_cards, present)
        rank     = result.hand_rank
        is_river = num_community == 5

        if rank.value >= HandRank.TWO_PAIR.value:
            return self._make_raise_by_rank(pot, big_blind, call_amount, rank)

        if rank == HandRank.PAIR:
            pair_rank = result.hand_value[0]

            if pair_rank >= 12:
                return self._make_raise_by_rank(pot, big_blind, call_amount, rank)

            if pair_rank >= 8:
                if call_amount == 0:
                    return self._make_raise_fraction(pot, big_blind, call_amount, 0.40)
                return self._call_or_bluff_or_fold(call_amount, pot, big_blind, 0.40)

            if call_amount == 0:
                return PlayerAction.CHECK, 0
            return self._call_or_bluff_or_fold(call_amount, pot, big_blind, 0.25)

        if rank.value < HandRank.PAIR.value:

            if self.last_preflop_aggressor and num_community == 3:
                if call_amount == 0 and random.random() < 0.6:
                    return self._make_raise_fraction(pot, big_blind, call_amount, 0.5)

            if call_amount == 0:
                bluff_chance = 0.15
                if random.random() < bluff_chance:
                    return self._make_raise_fraction(pot, big_blind, call_amount, 0.45)

            if call_amount > 0 and call_amount < pot * 0.25:
                if random.random() < 0.10:
                    return self._make_raise_fraction(pot, big_blind, call_amount, 0.60)

        # Include hole cards to check draws
        has_flush = self._has_flush_draw(self.hole_cards + present)
        has_straight = self._has_straight_draw(self.hole_cards + present)

        if call_amount == 0:
            if num_community == 3 and (has_flush or has_straight):
                bluff_prob = 0.35
                if self.state == "aggressive":
                    bluff_prob += 0.15

                if random.random() < bluff_prob:
                    return self._make_raise_fraction(pot, big_blind, call_amount, 0.5)

            return PlayerAction.CHECK, 0

        if is_river:
            if random.random() < 0.50:
                return self._make_raise_fraction(pot, big_blind, call_amount, 0.50)
            return PlayerAction.FOLD, 0

        if has_flush:
            return self._call_or_bluff_or_fold(call_amount, pot, big_blind, 0.25)

        if has_straight:
            return self._call_or_bluff_or_fold(call_amount, pot, big_blind, 0.20)

        if random.random() < 0.50:
            return self._make_raise_fraction(pot, big_blind, call_amount, 0.50)
        return PlayerAction.FOLD, 0

    _RANK_FRACTION = {
        HandRank.ROYAL_FLUSH:     1.00,
        HandRank.STRAIGHT_FLUSH:  1.00,
        HandRank.FOUR_OF_A_KIND:  1.00,
        HandRank.FULL_HOUSE:      0.90,
        HandRank.FLUSH:           0.80,
        HandRank.STRAIGHT:        0.75,
        HandRank.THREE_OF_A_KIND: 0.70,
        HandRank.TWO_PAIR:        0.60,
        HandRank.PAIR:            0.45,
    }

    def _make_raise_by_rank(self, pot, big_blind, call_amount, hand_rank):
        base_fraction = self._RANK_FRACTION.get(hand_rank, 0.50)
        fraction = min(base_fraction * (1.15 if self.state == "aggressive" else 1.0), 1.0)
        return self._make_raise_fraction(pot, big_blind, call_amount, fraction)

    def _make_raise_fraction(self, pot, big_blind, call_amount, fraction):
        current_bet_level = self.bet_amount + call_amount

        target_total = max(
            int(pot * fraction),
            current_bet_level + big_blind,
        )

        max_total = self.stack + self.bet_amount

        if target_total >= max_total:
            return PlayerAction.ALL_IN, self.stack

        if call_amount == 0 and self.bet_amount == 0:
            bet_amount = max(target_total, big_blind + 1)
            bet_amount = min(bet_amount, self.stack)

            if bet_amount >= self.stack:
                return PlayerAction.ALL_IN, self.stack

            return PlayerAction.BET, bet_amount

        else:
            raise_to = max(target_total, current_bet_level + big_blind)
            raise_to = min(raise_to, self.stack + self.bet_amount)

            if raise_to >= self.stack + self.bet_amount:
                return PlayerAction.ALL_IN, self.stack

            return PlayerAction.RAISE, raise_to

    def _pot_odds_ok(self, call_amount, pot, threshold=0.35):
        if call_amount <= 0:
            return True
        return call_amount / (pot + call_amount) < threshold

    def _chen_score(self, card1, card2):
        r1, r2 = card1.rank.value, card2.rank.value
        if r1 < r2:
            r1, r2 = r2, r1

        score_map = {14: 10, 13: 8, 12: 7, 11: 6}
        score = score_map.get(r1, r1 / 2.0)

        if r1 == r2:
            score = max(score * 2, 5)
        else:
            if card1.suit == card2.suit:
                score += 2

            gap = r1 - r2 - 1
            score += {0: 0, 1: -1, 2: -2, 3: -4}.get(gap, -5)

            if gap <= 1 and r1 < 12:
                score += 1

        return score

    def _has_flush_draw(self, cards):
        from collections import Counter
        return max(Counter(c.suit for c in cards).values(), default=0) >= 4

    def _has_straight_draw(self, cards):
        ranks = set(c.rank.value for c in cards)
        if 14 in ranks:
            ranks.add(1)
        ranks = sorted(ranks)
        for i in range(len(ranks) - 3):
            if ranks[i + 3] - ranks[i] <= 4:
                return True
        return False

    def _parse_community(self, game_state):
        result = []
        for idx in game_state[2:7]:
            if idx == 0:
                result.append(None)
            else:
                rank, suit = self.get_rank_suit(idx)
                result.append(Card(rank=Rank(rank), suit=Suit(suit)))
        return result

    def get_rank_suit(self, card_idx):
        suit = (card_idx - 1) // 13
        rank = card_idx + 1 - (suit * 13)
        return rank, suit
