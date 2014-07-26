from aqt import reviewer

##########################################################################

learningDeckNamePostfix = "::0. Learning"

def moveCardToDeck(self, did):
  self.card.did = did
  self.card.odid = 0
  self.card.flush()
  self.mw.reset()

def moveCard(self):
  if not self.card.odid:
    currentDeckName = self.mw.col.decks.name(self.card.did)
    if self.card.queue in (1, 3):
      if not currentDeckName.lower().endswith(learningDeckNamePostfix.lower()):
        moveCardToDeck(self, self.mw.col.decks.id(currentDeckName + learningDeckNamePostfix))
    elif self.card.queue == 2:
      if currentDeckName.lower().endswith(learningDeckNamePostfix.lower()):
        moveCardToDeck(self, self.mw.col.decks.id(currentDeckName[:-learningDeckNamePostfix.__len__()]))

def myAnswerCard(self, ease):
  "Reschedule card and show next."
  if self.mw.state != "review":
    # showing resetRequired screen; ignore key
    return
  if self.state != "answer":
    return
  if self.mw.col.sched.answerButtons(self.card) < ease:
    return
  self.mw.col.sched.answerCard(self.card, ease)
  moveCard(self)
  if self.card:
    self._answeredIds.append(self.card.id)
  self.mw.autosave()
  self.nextCard()

reviewer.Reviewer._answerCard = myAnswerCard

##########################################################################
