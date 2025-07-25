from django.core.exceptions import ValidationError
from django.db import models
from users.models import Team, User


class Game(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()

    class Meta:
        app_label = "tournaments"


class Scoring(models.Model):
    tournament = models.ForeignKey("Tournament", on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    score = models.IntegerField()

    class Meta:
        unique_together = ("tournament", "user")
        app_label = "tournaments"


class GameImage(models.Model):
    IMAGE_TYPE_CHOICES = (
        ("hero_banner", "Hero Banner"),
        ("cta_banner", "CTA Banner"),
        ("game_image", "Game Image"),
        ("thumbnail", "Thumbnail"),
        ("icon", "Icon"),
        ("slider", "Slider"),
        ("illustration", "Illustration"),
        ("promotional_banner", "Promotional Banner"),
    )
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="images")
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPE_CHOICES)
    image = models.ImageField(upload_to="game_images/")

    class Meta:
        app_label = "tournaments"

    def __str__(self):
        return f"{self.game.name} - {self.get_image_type_display()}"


class Tournament(models.Model):
    class Meta:
        app_label = "tournaments"
    TOURNAMENT_TYPE_CHOICES = (
        ("individual", "Individual"),
        ("team", "Team"),
    )
    type = models.CharField(
        max_length=20, choices=TOURNAMENT_TYPE_CHOICES, default="individual"
    )
    name = models.CharField(max_length=100)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_free = models.BooleanField(default=True)
    entry_fee = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    rules = models.TextField(blank=True)
    participants = models.ManyToManyField(
        User, through="Participant", related_name="tournaments", blank=True
    )
    teams = models.ManyToManyField(Team, related_name="tournaments", blank=True)
    creator = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="created_tournaments",
        null=True,
        blank=True,
    )
    countdown_start_time = models.DateTimeField(null=True, blank=True)
    required_verification_level = models.IntegerField(default=1)

    def clean(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError("End date must be after start date.")
        if not self.is_free and self.entry_fee is None:
            raise ValidationError("Entry fee must be set for paid tournaments.")
        if self.type == "individual" and self.teams.exists():
            raise ValidationError(
                "Individual tournaments cannot have team participants."
            )
        if self.type == "team" and self.participants.exists():
            raise ValidationError(
                "Team tournaments cannot have individual participants."
            )

    def __str__(self):
        return self.name


class Participant(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20,
        choices=(
            ("registered", "Registered"),
            ("checked_in", "Checked-in"),
            ("eliminated", "Eliminated"),
        ),
        default="registered",
    )

    class Meta:
        unique_together = ("user", "tournament")
        app_label = "tournaments"


class Match(models.Model):
    MATCH_TYPE_CHOICES = (
        ("individual", "Individual"),
        ("team", "Team"),
    )
    tournament = models.ForeignKey(
        Tournament, on_delete=models.CASCADE, related_name="matches"
    )
    match_type = models.CharField(
        max_length=20, choices=MATCH_TYPE_CHOICES, default="individual"
    )
    round = models.IntegerField()
    participant1_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="matches_as_participant1",
        null=True,
        blank=True,
    )
    participant2_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="matches_as_participant2",
        null=True,
        blank=True,
    )
    participant1_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="matches_as_participant1",
        null=True,
        blank=True,
    )
    participant2_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="matches_as_participant2",
        null=True,
        blank=True,
    )
    winner_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="won_matches",
        null=True,
        blank=True,
    )
    winner_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="won_matches",
        null=True,
        blank=True,
    )
    result_proof = models.ImageField(
        upload_to="private_result_proofs/", null=True, blank=True
    )
    is_confirmed = models.BooleanField(default=False)
    is_disputed = models.BooleanField(default=False)

    def clean(self):
        if self.match_type == "individual":
            if self.participant1_team or self.participant2_team:
                raise ValidationError(
                    "Individual matches cannot have team participants."
                )
            if not self.participant1_user or not self.participant2_user:
                raise ValidationError("Individual matches must have user participants.")
        elif self.match_type == "team":
            if self.participant1_user or self.participant2_user:
                raise ValidationError("Team matches cannot have user participants.")
            if not self.participant1_team or not self.participant2_team:
                raise ValidationError("Team matches must have team participants.")

    def __str__(self):
        if self.match_type == "individual":
            return f"{self.participant1_user} vs {self.participant2_user} - Tournament: {self.tournament}"
        else:
            return f"{self.participant1_team} vs {self.participant2_team} - Tournament: {self.tournament}"

    class Meta:
        app_label = "tournaments"


class Report(models.Model):
    REPORT_STATUS_CHOICES = (
        ("pending", "Pending"),
        ("resolved", "Resolved"),
        ("rejected", "Rejected"),
    )
    reporter = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_reports"
    )
    reported_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="received_reports"
    )
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    description = models.TextField()
    evidence = models.FileField(upload_to="report_evidence/", null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=REPORT_STATUS_CHOICES, default="pending"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report by {self.reporter.username} against {self.reported_user.username} in {self.match}"

    class Meta:
        app_label = "tournaments"


class WinnerSubmission(models.Model):
    SUBMISSION_STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )
    winner = models.ForeignKey(User, on_delete=models.CASCADE)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE)
    video = models.FileField(upload_to="winner_submissions/")
    status = models.CharField(
        max_length=20, choices=SUBMISSION_STATUS_CHOICES, default="pending"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Submission by {self.winner.username} for {self.tournament.name}"

    class Meta:
        app_label = "tournaments"
