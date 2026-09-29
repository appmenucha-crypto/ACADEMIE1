from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Formation, Bloc, AudioFile, VideoFile, ServiteurFormation

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role', {'fields': ('role',)}),
    )
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active', 'date_joined')
    list_filter = ('role', 'is_active', 'is_staff')
    search_fields = ('username', 'first_name', 'last_name', 'email')

class BlocInline(admin.TabularInline):
    model = Bloc
    extra = 1
    fields = ('name', 'order')

class AudioInline(admin.TabularInline):
    model = AudioFile
    extra = 1
    fields = ('file', 'order')

class VideoInline(admin.TabularInline):
    model = VideoFile
    extra = 1
    fields = ('file', 'order')

@admin.register(Formation)
class FormationAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'has_html_questionnaire', 'has_json_questionnaire')
    list_filter = ('created_at',)
    search_fields = ('name',)
    inlines = [BlocInline]

    @admin.display(boolean=True, ordering='questionnaire_html')
    def has_html_questionnaire(self, obj):
        return bool(obj.questionnaire_html)
    has_html_questionnaire.short_description = "QCM HTML importé"

    @admin.display(boolean=True, ordering='questionnaire_json')
    def has_json_questionnaire(self, obj):
        return bool(obj.questionnaire_json)
    has_json_questionnaire.short_description = "QCM JSON"

@admin.register(Bloc)
class BlocAdmin(admin.ModelAdmin):
    list_display = ('name', 'formation', 'order')
    list_filter = ('formation',)
    search_fields = ('name',)
    inlines = [AudioInline, VideoInline]

@admin.register(AudioFile)
class AudioFileAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'bloc', 'order')
    list_filter = ('bloc__formation', 'bloc')
    search_fields = ('bloc__name',)

@admin.register(VideoFile)
class VideoFileAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'bloc', 'order')
    list_filter = ('bloc__formation', 'bloc')
    search_fields = ('bloc__name',)

@admin.register(ServiteurFormation)
class ServiteurFormationAdmin(admin.ModelAdmin):
    list_display = ('serviteur', 'formation', 'score', 'statut', 'date_debut', 'date_soumission', 'has_html_responses')
    list_filter = ('statut', 'formation', 'date_debut')
    search_fields = ('serviteur__username', 'formation__name')
    readonly_fields = ('html_responses',)

    @admin.display(boolean=True)
    def has_html_responses(self, obj):
        return bool(obj.html_responses)
    has_html_responses.short_description = "Réponses HTML"

from .models_vertumetre import ServiteurVertumetre

@admin.register(ServiteurVertumetre)
class ServiteurVertumetreAdmin(admin.ModelAdmin):
    list_display = ('serviteur', 'submitted_at', 'is_submitted_recently')
    list_filter = ('submitted_at',)
    search_fields = ('serviteur__username', 'serviteur__first_name', 'serviteur__last_name')
    readonly_fields = ('answers', 'submitted_at')
